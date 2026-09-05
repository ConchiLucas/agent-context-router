import Link from "next/link";

import { getProjectScript, getProjectScripts } from "@/lib/api";
import { scriptKindLabel } from "@/lib/script-health";

type ProjectScriptsViewProps = Readonly<{
  projectSlug: string;
  selectedScriptSlug?: string;
  scriptHref: (scriptSlug: string) => string;
  subtitle?: string;
}>;

export async function ProjectScriptsView({
  projectSlug,
  selectedScriptSlug,
  scriptHref,
  subtitle = "Database-backed workspace scripts. This view is read-only.",
}: ProjectScriptsViewProps) {
  const listingResult = await Promise.allSettled([getProjectScripts(projectSlug)]);
  const listing = listingResult[0].status === "fulfilled" ? listingResult[0].value : null;
  const selected = selectedScriptSlug
    ? await getProjectScript(projectSlug, selectedScriptSlug).catch(() => null)
    : null;

  return (
    <>
      <header>
        <h1 className="page-title">Scripts</h1>
        <p className="page-subtitle">{subtitle}</p>
      </header>
      {listing === null ? (
        <p className="page-subtitle">Workspace scripts are unavailable.</p>
      ) : listing.scripts.length === 0 ? (
        <p className="page-subtitle">No workspace scripts are stored for this project yet.</p>
      ) : (
        <div className="script-split">
          <div className="script-list">
            {listing.scripts.map((script) => {
              const active = script.slug === selectedScriptSlug;
              return (
                <Link
                  className={`script-row ${active ? "active" : ""}`}
                  href={scriptHref(script.slug)}
                  key={script.id}
                >
                  <div className="script-row-main">
                    <strong>{script.name}</strong>
                    <span className="page-subtitle">{script.relative_path}</span>
                  </div>
                  <span className={`badge script-kind-${script.kind}`}>
                    {scriptKindLabel(script.kind)}
                  </span>
                </Link>
              );
            })}
          </div>
          <div className="script-detail panel">
            {selected ? (
              <>
                <div className="script-detail-heading">
                  <div>
                    <h2 className="section-title">{selected.name}</h2>
                    <p className="page-subtitle">{selected.relative_path}</p>
                  </div>
                  <span className={`badge script-kind-${selected.kind}`}>
                    {scriptKindLabel(selected.kind)}
                  </span>
                </div>
                {selected.description ? (
                  <p className="page-subtitle">{selected.description}</p>
                ) : null}
                <pre className="script-content">{selected.content}</pre>
              </>
            ) : (
              <p className="page-subtitle">Select a script to read its stored content.</p>
            )}
          </div>
        </div>
      )}
    </>
  );
}
