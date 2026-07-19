# 前端路由

本文件用于把前端页面、交互、布局和浏览器自测类任务路由到合适上下文。

## 适用任务

- 修改 Projects、Documents、Traces 等页面。
- 调整弹窗、关系图、卡片、筛选器或详情页布局。
- 检查前端调用后端 API 的链路。
- 用浏览器访问本地前端端口进行验证。

## 子路由

- `frontend_page`：页面结构、路由和组件入口。
- `frontend_interaction`：弹窗、返回、筛选和点击行为。
- `frontend_verification`：lint、build、浏览器自测和截图观察。

## 下一步

- 页面入口读 `frontend/app/`。
- 组件实现读 `frontend/components/`。
- API 类型和请求读 `frontend/lib/`。
- 样式读 `frontend/app/globals.css`。

修改前端后，按开发规范使用 Docker Compose 运行前端验证并重启前端服务。
