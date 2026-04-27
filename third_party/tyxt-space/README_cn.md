# TYXT 可视化空间 v1.5.0

- [English README / README.md](./README.md)

TYXT 可视化空间是 TYXT Local Agent 的 2D 可视化首页。它把本地 Agent 系统呈现为一个可以编辑的空间：房屋、家具、人物、房间名称、墙壁和交互区域都可以通过前端 UI 管理。

本次 v1.5.0 的重点是让可视化空间的数据结构稳定下来，并移除旧的 asset pack / remap 工作流。

## v1.5.0 重点更新

- 房屋主图统一来自 `public/assets/houses`。
- 家具素材统一来自 `public/assets/furnitures`。
- 场景数据保存在 `public/data`，包括房屋目录、家具目录、场景配置、场景地图和人物映射。
- 房间名称位置由前端 UI 拖拽保存。
- 墙壁范围由前端 UI 编辑，并用于从主图范围中扣除不可行走区域。
- 移动范围规则改为：主图可见范围 - 墙壁范围。
- 人物配置由 `public/data/agent-actors.json` 和 `src/data/scene-art.manifest.json` 管理。
- 旧的 `public/assets/packs` 和 `remap.html` 工作流已移除。
- 商店入口仅作为未来功能预留，v1.5.0 尚未实现商店编辑。

## 核心概念

### 房屋

房屋图片是可视化空间的主背景。

运行位置：

```text
public/assets/houses/
public/data/houses.json
public/data/scene-config.json
```

房屋图片建议使用 PNG 或 WebP。当前导入检查会校验图片尺寸，并要求与基准房屋保持一致的宽高比例。

### 家具

家具以方向素材的形式保存，并通过可视化编辑器摆放到场景中。

运行位置：

```text
public/assets/furnitures/
public/data/furnitures.json
public/data/scene-map.json
```

家具可以包含正面、左侧、右侧、背面素材。摆放位置、朝向、尺寸、碰撞行为和交互数据会保存到场景地图中。

### 人物

人物素材与房屋、家具数据分离管理。

运行位置：

```text
public/assets/generated/actors/
public/data/agent-actors.json
src/data/scene-art.manifest.json
```

默认人物变体是 `tyxt-emoji`。旧的 capy/cat 人物变体已经不再进入运行链路。

### 墙壁与移动范围

行走范围不再依赖 `reference-walkable.png`。

当前规则为：

```text
可行走范围 = 主图可见范围 - 墙壁范围
```

墙壁由前端 UI 编辑，作为角色移动和路径恢复的阻挡几何。

### 房间名称

房间名称位置由前端拖拽决定，并随场景地图保存。旧的 remap 工具已经删除。

### 商店

商店按钮/入口仅作为后续产品逻辑预留。v1.5.0 中没有开放商店编辑功能。

## 开发命令

```bash
npm install
npm run validate
npm run typecheck
npm run build
npm run dev
```

可选 QA 命令：

```bash
npm run qa:movement
npm run qa:visual:baseline
npm run qa:visual
```

QA 输出只用于本地检查，不应提交到仓库。

## 配置

公开配置入口是：

```text
clawlibrary.config.json
```

默认人物配置：

```json
{
  "actor": {
    "defaultVariantId": "tyxt-emoji"
  }
}
```

如需本地环境覆盖，可以使用 `.env`。该文件已被 Git 忽略。

## 公开数据文件

```text
public/data/houses.json        房屋目录
public/data/furnitures.json    家具目录
public/data/scene-config.json  当前房屋/基准房屋配置
public/data/scene-map.json     墙壁、房名、家具和交互数据
public/data/agent-actors.json  Agent 到人物变体的映射
```

用户自己的角色绑定会写入：

```text
public/data/agent-actors.local.json
```

这个本地覆盖文件已被 Git 忽略，所以在 UI 里调整人物绑定不会再产生源代码管理改动。

## 隐私说明

不要提交本地运行数据、生成日志、`.env` 或本机配置。根仓库 `.gitignore` 与当前包 `.gitignore` 已默认排除这些内容。

## License

代码采用 MIT License：

- `/LICENSE`

素材采用 CC BY-NC-SA 4.0：

- `/LICENSE-ASSETS.md`
- 允许在署名条件下进行非商用分享、改编和再分发。
- 如果你分发改编后的素材，需要继续使用同样的许可。
- 如果你要将本项目用于商业用途，请替换掉仓库内附带的美术素材，或另行取得原素材授权。
