"""基于 Java 语法树判定表关联基数。

判定思路建立在一个非对称性上：证明 1:1 需要「不存在两条」的全称断言，证明 1:N 需要
「存在两条」的存在性证据。单点证据只能给出上界，因此本分析器先按实体类型枚举一张表的
全部写入入口，再用运行时已验证的证据（不带合并函数的 Collectors.toMap）做交叉确认。

必须按类型解析而不是按变量名匹配：shipping / highway / railway 三个模块都有名为
cargoDao 的字段，但指向 cs_dsly_shipping_cargo、cs_dsly_highway_cargo、
cs_dsly_railway_cargo 三张不同的表，且后两者使用 batchInsert 而前者不用。
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_java
from tree_sitter import Language, Node, Parser

_LANGUAGE = Language(tree_sitter_java.language())

# ModuleBaseModel(@MappedSuperclass) 提供的公共字段，不参与关联判定。
BASE_MODEL_FIELDS = frozenset(
    {"id", "tenancy", "companyId", "creator", "createTime", "modifier", "modifyTime"}
)
PUBLIC_COLUMNS = frozenset(
    {
        "id",
        "deleted",
        "tenancy",
        "company_id",
        "creator",
        "create_time",
        "modifier",
        "modify_time",
    }
)

# 框架写入方法。单对象写入至多产生一行；批量写入天然允许一父多子。
SINGLE_WRITE_METHODS = frozenset({"insert", "update", "updateById", "saveOrUpdate", "save"})
BATCH_WRITE_METHODS = frozenset(
    {"batchInsert", "batchInsertToSqlExecution", "preSaveList", "saveAll", "updateByIds"}
)
WRITE_METHODS = SINGLE_WRITE_METHODS | BATCH_WRITE_METHODS
# 只有新建行的写法才决定基数上界，纯更新不新增行。
CREATING_METHODS = frozenset(
    {"insert", "saveOrUpdate", "save", "batchInsert", "batchInsertToSqlExecution", "preSaveList"}
)

DAO_BASE = "ModuleBaseDaoSupport"
SERVICE_BASE = "ModuleBaseServiceSupport"

_DTO_SUFFIXES = (
    "AdminPageCondition",
    "PortalPageCondition",
    "PageCondition",
    "AdminCondition",
    "PortalCondition",
    "AdminQuery",
    "PortalQuery",
    "AdminItem",
    "PortalItem",
    "ChildQuery",
    "ChildItem",
    "Condition",
    "Query",
    "Item",
)


def to_snake(name: str) -> str:
    """Hibernate 默认命名策略：camelCase 转 snake_case。"""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def text(node: Node | None) -> str:
    return "" if node is None else node.text.decode("utf-8", "replace")


def walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def find_child(node: Node, node_type: str) -> Node | None:
    for child in node.named_children:
        if child.type == node_type:
            return child
    return None


def generic_arguments(superclass: Node | None) -> list[str]:
    """从 `extends Base<A, B>` 取出泛型实参的简单名。"""
    if superclass is None:
        return []
    raw = text(superclass)
    match = re.search(r"<(.+)>", raw, re.DOTALL)
    if not match:
        return []
    depth = 0
    parts: list[str] = []
    buffer = ""
    for char in match.group(1):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(buffer)
            buffer = ""
            continue
        buffer += char
    parts.append(buffer)
    return [part.strip().split("<")[0] for part in parts if part.strip()]


def superclass_name(superclass: Node | None) -> str:
    if superclass is None:
        return ""
    raw = text(superclass).replace("extends", "", 1).strip()
    return raw.split("<")[0].split(".")[-1].strip()


@dataclass
class EntityInfo:
    simple_name: str
    table: str
    source: Path
    fields: dict[str, str] = field(default_factory=dict)
    """java 字段名 -> 列名，已剔除公共字段。"""


@dataclass
class WriteSite:
    table: str
    entity: str
    method: str
    receiver: str
    argument: str
    path: Path
    line: int
    enclosing_method: str
    is_batch: bool
    loop_shape: str
    """single | per_parent_iteration | writes_loop_collection | unknown_loop"""
    mentioned_identifiers: frozenset[str] = frozenset()
    """所在方法体出现过的标识符，用于把写入入口归属到具体外键列。"""

    def touches(self, java_field: str) -> bool:
        setter = "set" + java_field[0].upper() + java_field[1:]
        getter = "get" + java_field[0].upper() + java_field[1:]
        return bool({java_field, setter, getter} & self.mentioned_identifiers)

    @property
    def creates_rows(self) -> bool:
        return self.method in CREATING_METHODS

    @property
    def method_key(self) -> tuple[str, str]:
        return (str(self.path), self.enclosing_method)


@dataclass(frozen=True)
class LoopSetter:
    """循环体内对某个字段的赋值，区分批内恒定与逐行变化。

    批量写入只证明一次调用能写多行，只有当某列在批内取值恒定（典型是父键）时，
    才能推出该列是 N:1。像 file_id 这种逐行不同的列，批量写入不构成任何基数证据。
    """

    path: str
    method: str
    java_field: str
    invariant: bool


@dataclass
class CardinalityEvidence:
    kind: str
    """strict_to_map | loose_to_map | grouping_by | finder_single | finder_list | condition_pair"""
    dto: str
    accessor: str
    detail: str
    path: Path
    line: int


@dataclass
class Verdict:
    table: str
    column: str
    java_field: str
    target_tables: list[str]
    cardinality: str
    confidence: str
    reasons: list[str]
    write_sites: list[WriteSite]
    evidence: list[CardinalityEvidence]


class JavaIndex:
    """实体、DAO、Service 的类型索引，跨模块解析用。"""

    def __init__(self) -> None:
        self.entities: dict[str, EntityInfo] = {}
        self.dao_to_entity: dict[str, str] = {}
        self.service_to_entity: dict[str, str] = {}
        self.service_parent: dict[str, str] = {}
        self.parser = Parser(_LANGUAGE)

    def parse(self, path: Path) -> Node | None:
        try:
            tree = self.parser.parse(path.read_bytes())
        except OSError:
            return None
        return tree.root_node

    def index_file(self, path: Path) -> None:
        root = self.parse(path)
        if root is None:
            return
        for node in walk(root):
            if node.type != "class_declaration":
                continue
            name = text(node.child_by_field_name("name"))
            if not name:
                continue
            superclass = node.child_by_field_name("superclass")
            base = superclass_name(superclass)
            args = generic_arguments(superclass)

            if base == DAO_BASE and args:
                self.dao_to_entity[name] = args[0]
            elif name.endswith("Dao") and args:
                self.dao_to_entity.setdefault(name, args[0])

            if base == SERVICE_BASE and len(args) >= 2:
                self.service_to_entity[name] = args[1]
            elif base:
                self.service_parent[name] = base

            table = self._entity_table(node)
            if table:
                self.entities[name] = EntityInfo(
                    simple_name=name,
                    table=table,
                    source=path,
                    fields=self._entity_fields(node),
                )

    def _entity_table(self, class_node: Node) -> str:
        has_entity = False
        table = ""
        for child in class_node.named_children:
            if child.type != "modifiers":
                continue
            for annotation in child.named_children:
                if annotation.type not in {"annotation", "marker_annotation"}:
                    continue
                annotation_name = text(annotation.child_by_field_name("name"))
                if annotation_name == "Entity":
                    has_entity = True
                elif annotation_name == "Table":
                    match = re.search(r'name\s*=\s*"([^"]+)"', text(annotation))
                    if match:
                        table = match.group(1)
        return table if has_entity and table else ""

    def _entity_fields(self, class_node: Node) -> dict[str, str]:
        body = class_node.child_by_field_name("body")
        result: dict[str, str] = {}
        if body is None:
            return result
        for member in body.named_children:
            if member.type != "field_declaration":
                continue
            modifiers = find_child(member, "modifiers")
            modifier_text = text(modifiers)
            if "static" in modifier_text or "transient" in modifier_text:
                continue
            if "@Transient" in modifier_text:
                continue
            for declarator in member.named_children:
                if declarator.type != "variable_declarator":
                    continue
                java_name = text(declarator.child_by_field_name("name"))
                if not java_name or java_name in BASE_MODEL_FIELDS:
                    continue
                column = to_snake(java_name)
                if column in PUBLIC_COLUMNS:
                    continue
                result[java_name] = column
        return result

    def resolve_service_entity(self, service: str, depth: int = 0) -> str:
        if depth > 6:
            return ""
        if service in self.service_to_entity:
            return self.service_to_entity[service]
        parent = self.service_parent.get(service)
        if not parent:
            return ""
        return self.resolve_service_entity(parent, depth + 1)

    def dto_to_entity(self, dto: str) -> str:
        if dto in self.entities:
            return dto
        for suffix in _DTO_SUFFIXES:
            if dto.endswith(suffix) and len(dto) > len(suffix):
                stem = dto[: -len(suffix)]
                if stem in self.entities:
                    return stem
        return ""


class FileAnalyzer:
    """单文件分析：注入字段解析、写入入口抽取、基数证据抽取。"""

    def __init__(self, index: JavaIndex, path: Path) -> None:
        self.index = index
        self.path = path
        self.root = index.parse(path)
        self.write_sites: list[WriteSite] = []
        self.evidence: list[CardinalityEvidence] = []
        self.loop_setters: set[LoopSetter] = set()

    def run(self) -> None:
        if self.root is None:
            return
        for node in walk(self.root):
            if node.type == "class_declaration":
                self._analyze_class(node)

    def _analyze_class(self, class_node: Node) -> None:
        class_name = text(class_node.child_by_field_name("name"))
        body = class_node.child_by_field_name("body")
        if body is None:
            return

        # 字段类型表：变量名 -> 声明类型，用于把 cargoDao 绑定到具体实体。
        var_types: dict[str, str] = {}
        for member in body.named_children:
            if member.type != "field_declaration":
                continue
            declared = text(member.child_by_field_name("type")).split("<")[0].split(".")[-1]
            for declarator in member.named_children:
                if declarator.type == "variable_declarator":
                    var_types[text(declarator.child_by_field_name("name"))] = declared

        own_entity = self.index.resolve_service_entity(class_name)

        # 实体字段常在 buildXxx(...) 构建器里赋值，需要把构建器的标识符并进调用方，
        # 否则写入入口无法归属到具体外键列。
        method_identifiers: dict[str, frozenset[str]] = {}
        for member in body.named_children:
            if member.type != "method_declaration":
                continue
            member_body = member.child_by_field_name("body")
            if member_body is None:
                continue
            method_identifiers[text(member.child_by_field_name("name"))] = frozenset(
                re.findall(r"[A-Za-z_]\w*", text(member_body))
            )

        for member in body.named_children:
            if member.type not in {"method_declaration", "constructor_declaration"}:
                continue
            self._analyze_method(member, var_types, own_entity, method_identifiers)

    def _analyze_method(
        self,
        method_node: Node,
        class_var_types: dict[str, str],
        own_entity: str,
        method_identifiers: dict[str, frozenset[str]],
    ) -> None:
        method_name = text(method_node.child_by_field_name("name"))
        body = method_node.child_by_field_name("body")
        self._collect_finder_shape(method_node, method_name)
        if body is None:
            return

        mentioned = frozenset(re.findall(r"[A-Za-z_]\w*", text(body)))

        var_types = dict(class_var_types)
        # 局部变量的初始化调用，用于把构建器方法体的标识符追加到写入入口上。
        var_init_call: dict[str, str] = {}
        for node in walk(body):
            if node.type != "local_variable_declaration":
                continue
            declared = text(node.child_by_field_name("type"))
            simple = declared.split("<")[0].split(".")[-1]
            for declarator in node.named_children:
                if declarator.type != "variable_declarator":
                    continue
                name = text(declarator.child_by_field_name("name"))
                var_types[name] = "List" if declared.startswith("List<") else simple
                value = declarator.child_by_field_name("value")
                if value is not None and value.type == "method_invocation":
                    var_init_call[name] = text(value.child_by_field_name("name"))

        for node in walk(body):
            if node.type != "method_invocation":
                continue
            self._maybe_write_site(
                node,
                var_types,
                own_entity,
                method_name,
                body,
                mentioned,
                var_init_call,
                method_identifiers,
            )
            self._maybe_collector_evidence(node)
            self._maybe_condition_pair(node)

        self._collect_loop_setters(body, method_name)

    def _collect_loop_setters(self, body: Node, method_name: str) -> None:
        for node in walk(body):
            loop_var = ""
            if node.type == "enhanced_for_statement":
                loop_var = text(node.child_by_field_name("name"))
                loop_body = node.child_by_field_name("body")
            elif node.type == "lambda_expression":
                parameters = node.child_by_field_name("parameters")
                loop_var = text(parameters) if parameters is not None else ""
                loop_body = node.child_by_field_name("body")
            else:
                continue
            if loop_body is None or not loop_var or not loop_var.isidentifier():
                continue

            for inner in walk(loop_body):
                if inner.type != "method_invocation":
                    continue
                setter = text(inner.child_by_field_name("name"))
                match = re.fullmatch(r"set([A-Z]\w*)", setter)
                if not match:
                    continue
                java_field = match.group(1)[0].lower() + match.group(1)[1:]
                if not java_field.endswith(("Id", "No")):
                    continue
                arguments = inner.child_by_field_name("arguments")
                argument_text = text(arguments)
                # 取值引用了循环变量就是逐行变化，否则整批共用同一个值。
                invariant = not re.search(rf"\b{re.escape(loop_var)}\b", argument_text)
                self.loop_setters.add(
                    LoopSetter(
                        path=str(self.path),
                        method=method_name,
                        java_field=java_field,
                        invariant=invariant,
                    )
                )

    def _maybe_write_site(
        self,
        call: Node,
        var_types: dict[str, str],
        own_entity: str,
        enclosing_method: str,
        method_body: Node,
        mentioned: frozenset[str],
        var_init_call: dict[str, str],
        method_identifiers: dict[str, frozenset[str]],
    ) -> None:
        name = text(call.child_by_field_name("name"))
        if name not in WRITE_METHODS:
            return
        receiver_node = call.child_by_field_name("object")
        receiver = text(receiver_node)

        entity = ""
        if receiver_node is None or receiver in {"this", "super"}:
            entity = own_entity
        else:
            declared = var_types.get(receiver, "")
            entity = self.index.dao_to_entity.get(declared, "")
            if not entity:
                service_entity = self.index.resolve_service_entity(declared)
                entity = service_entity
        if not entity or entity not in self.index.entities:
            return

        arguments = call.child_by_field_name("arguments")
        arg_nodes = [] if arguments is None else list(arguments.named_children)
        first_arg = text(arg_nodes[0]) if arg_nodes else ""
        arg_root = re.split(r"[.(\[]", first_arg)[0] if first_arg else ""

        is_batch = name in BATCH_WRITE_METHODS or var_types.get(arg_root) == "List"
        loop_shape = self._loop_shape(call, arg_root, method_body)

        effective = set(mentioned)
        builder = var_init_call.get(arg_root)
        if builder and builder in method_identifiers:
            effective |= method_identifiers[builder]

        self.write_sites.append(
            WriteSite(
                table=self.index.entities[entity].table,
                entity=entity,
                method=name,
                receiver=receiver or "this",
                argument=first_arg[:80],
                path=self.path,
                line=call.start_point[0] + 1,
                enclosing_method=enclosing_method,
                is_batch=is_batch,
                loop_shape=loop_shape,
                mentioned_identifiers=frozenset(effective),
            )
        )

    def _loop_shape(self, call: Node, arg_root: str, method_body: Node) -> str:
        """区分 1:1 与 1:N 的分水岭。

        写入的对象若来自被遍历的集合，说明一个父键对应多个子行；若是在循环体内新建、
        每轮一个，说明遍历的是父集合，每个父只建一个子行。
        """
        loop_vars: list[str] = []
        loop_nodes: list[Node] = []
        node: Node | None = call.parent
        while node is not None and node != method_body.parent:
            if node.type == "enhanced_for_statement":
                loop_vars.append(text(node.child_by_field_name("name")))
                loop_nodes.append(node)
            elif node.type == "for_statement":
                loop_nodes.append(node)
            elif node.type == "lambda_expression":
                parameters = node.child_by_field_name("parameters")
                if parameters is not None:
                    loop_vars.extend(
                        text(child) for child in parameters.named_children if text(child)
                    )
                else:
                    loop_vars.append(text(node.child_by_field_name("parameter")))
                loop_nodes.append(node)
            node = node.parent

        if not loop_nodes:
            return "single"
        if arg_root and arg_root in loop_vars:
            return "writes_loop_collection"
        innermost = loop_nodes[0]
        for inner in walk(innermost):
            if inner.type != "local_variable_declaration":
                continue
            for declarator in inner.named_children:
                if declarator.type != "variable_declarator":
                    continue
                if text(declarator.child_by_field_name("name")) == arg_root:
                    return "per_parent_iteration"
        return "unknown_loop"

    def _maybe_collector_evidence(self, call: Node) -> None:
        name = text(call.child_by_field_name("name"))
        if name not in {"toMap", "groupingBy"}:
            return
        arguments = call.child_by_field_name("arguments")
        if arguments is None:
            return
        arg_nodes = list(arguments.named_children)
        if not arg_nodes:
            return
        key_arg = text(arg_nodes[0])
        match = re.match(r"([\w.]+)::get(\w+)", key_arg)
        if not match:
            return
        dto = match.group(1).split(".")[-1]
        accessor = match.group(2)
        accessor_field = accessor[0].lower() + accessor[1:]

        if name == "groupingBy":
            kind = "grouping_by"
            detail = "按外键分组，作者认为可能一父多子"
        elif len(arg_nodes) >= 3:
            kind = "loose_to_map"
            detail = "带合并函数，作者预见重复后降级取一条"
        else:
            kind = "strict_to_map"
            detail = "无合并函数，键重复必抛 IllegalStateException，生产未崩即数据已验证唯一"

        self.evidence.append(
            CardinalityEvidence(
                kind=kind,
                dto=dto,
                accessor=accessor_field,
                detail=detail,
                path=self.path,
                line=call.start_point[0] + 1,
            )
        )

    def _maybe_condition_pair(self, call: Node) -> None:
        if text(call.child_by_field_name("name")) != "andEqual":
            return
        arguments = call.child_by_field_name("arguments")
        if arguments is None:
            return
        arg_nodes = list(arguments.named_children)
        if len(arg_nodes) < 2:
            return
        match = re.match(r"([\w.]+)::get(\w+)", text(arg_nodes[0]))
        if not match:
            return
        accessor = match.group(2)
        self.evidence.append(
            CardinalityEvidence(
                kind="condition_pair",
                dto=match.group(1).split(".")[-1],
                accessor=accessor[0].lower() + accessor[1:],
                detail=f"右值 {text(arg_nodes[1])[:60]}",
                path=self.path,
                line=call.start_point[0] + 1,
            )
        )

    def _collect_finder_shape(self, method_node: Node, method_name: str) -> None:
        if not method_name.startswith("findBy") or method_name in {"findById", "findByIds"}:
            return
        return_type = text(method_node.child_by_field_name("type"))
        stem = method_name[len("findBy") :]
        if not stem:
            return
        accessor_field = stem[0].lower() + stem[1:]
        is_list = return_type.startswith("List<")
        self.evidence.append(
            CardinalityEvidence(
                kind="finder_list" if is_list else "finder_single",
                dto="",
                accessor=accessor_field.rstrip("s") if is_list else accessor_field,
                detail=f"{return_type} {method_name}(...)",
                path=self.path,
                line=method_node.start_point[0] + 1,
            )
        )


def iter_java_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.java"):
        parts = set(path.parts)
        if "target" in parts or "build" in parts or "node_modules" in parts:
            continue
        yield path


def build_index(root: Path) -> JavaIndex:
    index = JavaIndex()
    for path in iter_java_files(root):
        index.index_file(path)
    return index


@dataclass
class AnalysisResult:
    writes: list[WriteSite] = field(default_factory=list)
    evidence: list[CardinalityEvidence] = field(default_factory=list)
    loop_setters: set[LoopSetter] = field(default_factory=set)


def analyze(index: JavaIndex, root: Path) -> AnalysisResult:
    result = AnalysisResult()
    for path in iter_java_files(root):
        analyzer = FileAnalyzer(index, path)
        analyzer.run()
        result.writes.extend(analyzer.write_sites)
        result.evidence.extend(analyzer.evidence)
        result.loop_setters |= analyzer.loop_setters
    return result


def is_own_business_key(owner: str, java_field: str) -> bool:
    """列名指向自己所在的实体时，它是本表的业务主键而不是外键。

    cs_dsly_shipping_carrier_order.carrier_order_no 是这张表自己的单号，若不排除会被
    命名解析错配到 cs_dsly_highway_carrier_order 之类的同名兄弟表上。

    只有 *No / *Code 才可能是自身业务键：这套框架的主键恒为裸 id，*Id 一律是外键。
    否则 cs_dsly_shipping_cargo.cargo_id 这种指向主数据的外键会被误杀。
    """
    if not java_field.endswith(("No", "Code")):
        return False
    stem = re.sub(r"(No|Code)$", "", java_field)
    if not stem:
        return False
    return owner.endswith(stem[0].upper() + stem[1:])


def resolve_targets(index: JavaIndex, owner: str, java_field: str) -> list[str]:
    """按命名从实体索引里找外键指向的表，返回全部候选以便人工判定歧义。"""
    stem = re.sub(r"(Id|No|Code)$", "", java_field)
    if not stem or is_own_business_key(owner, java_field):
        return []
    owner_prefix = owner_module_prefix(index, owner)
    exact: list[str] = []
    loose: list[str] = []
    for name, info in index.entities.items():
        if name == owner:
            continue
        if name == stem or name.endswith(stem[0].upper() + stem[1:]):
            bucket = exact if owner_module_prefix(index, name) == owner_prefix else loose
            bucket.append(info.table)
    return sorted(set(exact)) or sorted(set(loose))


def owner_module_prefix(index: JavaIndex, entity: str) -> str:
    info = index.entities.get(entity)
    if info is None:
        return ""
    table = info.table
    parts = table.split("_")
    return "_".join(parts[:3]) if len(parts) > 3 else table


def build_verdicts(index: JavaIndex, result: AnalysisResult, tables: set[str]) -> list[Verdict]:
    writes_by_table: dict[str, list[WriteSite]] = defaultdict(list)
    # 同一方法内创建了哪些表，用于判断父键是不是本次调用新产生的。
    created_by_method: dict[tuple[str, str], set[str]] = defaultdict(set)
    for site in result.writes:
        writes_by_table[site.table].append(site)
        if site.creates_rows:
            created_by_method[site.method_key].add(site.table)

    evidence_by_entity_field: dict[tuple[str, str], list[CardinalityEvidence]] = defaultdict(list)
    for item in result.evidence:
        entity = index.dto_to_entity(item.dto) if item.dto else ""
        evidence_by_entity_field[(entity, item.accessor)].append(item)

    verdicts: list[Verdict] = []
    for entity, info in sorted(index.entities.items(), key=lambda kv: kv[1].table):
        if info.table not in tables:
            continue
        table_writes = writes_by_table.get(info.table, [])
        for java_field, column in sorted(info.fields.items()):
            if not re.search(r"(Id|No)$", java_field):
                continue
            if is_own_business_key(entity, java_field):
                continue
            field_evidence = list(evidence_by_entity_field.get((entity, java_field), []))
            field_evidence += [
                item
                for item in evidence_by_entity_field.get(("", java_field), [])
                if item.path.parent == info.source.parent.parent / "dao"
                or entity.lower() in item.path.stem.lower()
            ]
            verdicts.append(
                _decide(
                    index=index,
                    entity=entity,
                    info=info,
                    java_field=java_field,
                    column=column,
                    table_writes=table_writes,
                    field_evidence=field_evidence,
                    created_by_method=created_by_method,
                    loop_setters=result.loop_setters,
                )
            )
    return verdicts


def _parent_key_freshness(
    creating_sites: list[WriteSite],
    targets: list[str],
    created_by_method: dict[tuple[str, str], set[str]],
) -> tuple[str, str]:
    """判断父键是本次调用新产生的，还是从已有数据里选来的可复用值。

    这是写入入口枚举法最容易出错的地方：枚举只能约束单次调用创建几个子行，
    约束不了同一个父键被多少次调用复用。父键若指向预先存在的主数据（如货物类别），
    每次调用都能挑同一个值，基数就是 N:1 而不是 1:1。

    唯一可靠的新鲜度信号是父行在同一方法内被创建。不能用「方法里调过序列生成器」代替：
    handleCreateDispatch 生成的是运单自己的单号，而不是它引用的承运单号。
    """
    if not creating_sites:
        return "unknown", "没有创建入口，无法判断父键来源"
    if not targets:
        return "unknown", "目标表未解析，无法判断父键来源"

    fresh = sum(
        1
        for site in creating_sites
        if any(target in created_by_method.get(site.method_key, set()) for target in targets)
    )

    if fresh == len(creating_sites):
        return "fresh", "每处创建入口都在同一方法内新建父行，父键不可复用"
    if fresh == 0:
        return "reusable", "父行在别处已存在，父键从入参或查询取得，可被多次调用复用"
    return "mixed", f"{fresh}/{len(creating_sites)} 处创建入口父键是新生成的，其余可复用"


def _decide_from_evidence(
    *,
    info: EntityInfo,
    column: str,
    java_field: str,
    targets: list[str],
    kinds: set[str],
    field_evidence: list[CardinalityEvidence],
    table_write_count: int,
) -> Verdict:
    """写入入口归属不到该列时，退回到读取侧与内存聚合证据。

    不带合并函数的 Collectors.toMap 本身就是运行时验证过的唯一性断言，不依赖写入枚举；
    groupingBy 与返回 List 的 finder 只能给出作者意图，置信度相应下调。
    """
    reasons = [
        f"该表 {table_write_count} 处写入入口都归属不到 {java_field}，"
        "赋值可能跨越多层构建器，改用读取侧证据判定"
    ]
    if "strict_to_map" in kinds:
        reasons.append("存在不带合并函数的 Collectors.toMap 且生产运行未崩，唯一性已被运行时验证")
        cardinality, confidence = "one_to_one", "runtime"
    elif "grouping_by" in kinds or "finder_list" in kinds:
        reasons.append("存在 groupingBy 或返回 List 的 finder，读取侧按一父多子处理")
        cardinality, confidence = "many_to_one", "intent"
    elif "loose_to_map" in kinds:
        reasons.append("仅有带合并函数的 toMap，作者预见过重复，倾向一父多子但未证实")
        cardinality, confidence = "unknown", "low"
    elif "finder_single" in kinds:
        reasons.append("仅有返回单体的 finder，读取侧按一父一子处理但缺少唯一性保证")
        cardinality, confidence = "one_to_one", "intent"
    else:
        reasons.append("没有可用的基数证据")
        cardinality, confidence = "unknown", "none"

    if len(targets) > 1:
        reasons.append(f"目标表命名存在歧义，候选 {len(targets)} 张，需人工确认")

    return Verdict(
        table=info.table,
        column=column,
        java_field=java_field,
        target_tables=targets,
        cardinality=cardinality,
        confidence=confidence,
        reasons=reasons,
        write_sites=[],
        evidence=field_evidence,
    )


def _decide(
    *,
    index: JavaIndex,
    entity: str,
    info: EntityInfo,
    java_field: str,
    column: str,
    table_writes: list[WriteSite],
    field_evidence: list[CardinalityEvidence],
    created_by_method: dict[tuple[str, str], set[str]],
    loop_setters: set[LoopSetter],
) -> Verdict:
    reasons: list[str] = []
    kinds = {item.kind for item in field_evidence}
    targets = resolve_targets(index, entity, java_field)

    # 一张表可能兼做多种用途（cs_dsly_shipping_cargo 同时承载承运货物和运单货物），
    # 不同外键列由不同入口填充，所以只统计确实提到该列的入口。
    column_sites = [site for site in table_writes if site.touches(java_field)]
    batch_sites = [site for site in column_sites if site.is_batch]
    collection_sites = [
        site for site in column_sites if site.loop_shape == "writes_loop_collection"
    ]
    unknown_sites = [site for site in column_sites if site.loop_shape == "unknown_loop"]
    creating_sites = [site for site in column_sites if site.creates_rows]

    if not table_writes:
        return Verdict(
            table=info.table,
            column=column,
            java_field=java_field,
            target_tables=targets,
            cardinality="unknown",
            confidence="none",
            reasons=["分析范围内没有找到写入入口，可能由其他模块或外部接口写入"],
            write_sites=[],
            evidence=field_evidence,
        )
    if not column_sites or not creating_sites:
        return _decide_from_evidence(
            info=info,
            column=column,
            java_field=java_field,
            targets=targets,
            kinds=kinds,
            field_evidence=field_evidence,
            table_write_count=len(table_writes),
        )

    freshness, freshness_reason = _parent_key_freshness(creating_sites, targets, created_by_method)

    multi_row_sites = batch_sites + collection_sites
    invariant_sites = [
        site
        for site in multi_row_sites
        if LoopSetter(str(site.path), site.enclosing_method, java_field, True) in loop_setters
    ]
    varying_sites = [
        site
        for site in multi_row_sites
        if LoopSetter(str(site.path), site.enclosing_method, java_field, False) in loop_setters
    ]

    if invariant_sites:
        reasons.append(
            f"{len(invariant_sites)} 处批量写入的循环体内把 {java_field} 赋成批内恒定值，"
            "一个父键对应整批子行"
        )
        cardinality = "many_to_one"
        confidence = "confirmed"
    elif multi_row_sites and varying_sites:
        reasons.append(
            f"虽有 {len(multi_row_sites)} 处批量写入，但 {java_field} 在批内逐行变化，"
            "批量本身不构成基数证据"
        )
        cardinality = "unknown"
        confidence = "low"
    elif multi_row_sites and freshness != "reusable":
        reasons.append(
            f"存在批量写入入口 {len(batch_sites)} 处、写入循环集合 {len(collection_sites)} 处，"
            f"但无法确认 {java_field} 在批内是否恒定，需人工确认"
        )
        cardinality = "unknown"
        confidence = "low"
    elif freshness == "reusable":
        reasons.append(freshness_reason)
        cardinality = "many_to_one"
        confidence = "confirmed"
    elif freshness == "unknown":
        reasons.append(freshness_reason)
        cardinality = "unknown"
        confidence = "low"
    elif freshness == "mixed":
        reasons.append(freshness_reason)
        cardinality = "unknown"
        confidence = "low"
    elif "strict_to_map" in kinds:
        reasons.append(freshness_reason)
        reasons.append(
            f"全部 {len(creating_sites)} 处创建入口均为单对象写入，且存在不带合并函数的 "
            "Collectors.toMap 在生产运行未崩，唯一性已被运行时验证"
        )
        cardinality = "one_to_one"
        confidence = "confirmed"
    elif unknown_sites:
        reasons.append(
            f"有 {len(unknown_sites)} 处写入位于循环内但无法判定写的是父还是子，需人工确认"
        )
        cardinality = "unknown"
        confidence = "low"
    else:
        reasons.append(freshness_reason)
        reasons.append(
            f"全部 {len(creating_sites)} 处创建入口均为单对象写入，上界为 1，但缺少运行时验证证据"
        )
        cardinality = "one_to_one"
        confidence = "upper_bound"

    if "loose_to_map" in kinds:
        reasons.append("存在带合并函数的 toMap，作者预见过重复，实际可能是一父多子")
    if "grouping_by" in kinds:
        reasons.append("存在 groupingBy 分组，作者按一父多子处理")
    if "finder_list" in kinds:
        reasons.append("存在返回 List 的 finder，读取侧按一父多子处理")
    if "finder_single" in kinds:
        reasons.append("存在返回单体的 finder，读取侧按一父一子处理")

    if len(targets) > 1:
        reasons.append(f"目标表命名存在歧义，候选 {len(targets)} 张，需人工确认")

    return Verdict(
        table=info.table,
        column=column,
        java_field=java_field,
        target_tables=targets,
        cardinality=cardinality,
        confidence=confidence,
        reasons=reasons,
        write_sites=column_sites,
        evidence=field_evidence,
    )
