# 🌸 语晴论坛

> 语晴制作 · 二外国际论坛

基于 Flask + SQLite 的轻量级社区论坛系统。

## 功能特性

- 📝 **发帖/回帖** - 支持文字、图片、视频，匿名发布
- 👍 **点赞系统** - 帖子和回复均可点赞
- 🏆 **排行榜** - 风云人物榜、厨神争霸榜
- 🔍 **搜索功能** - 按内容、用户、版块搜索
- 👤 **用户主页** - 个人资料、我的帖子、粉丝关注
- 🔔 **通知系统** - @提及、回复通知
- ⭐ **收藏功能** - 收藏喜欢的帖子
- 🔒 **管理后台** - 用户管理、版块管理、内容管理、敏感词过滤
- 📱 **响应式设计** - 适配手机和桌面端

## 技术栈

- **后端**：Python 3.12 / Flask 3.0 / SQLite (WAL模式)
- **前端**：Jinja2 模板 / 原生 JavaScript / CSS
- **部署**：支持 systemd 服务、screen 或 nohup

## 快速部署

```bash
# 克隆仓库
git clone https://github.com/YTCodeQwQ/YuQing-Forum.git
cd YuQing-Forum

# 安装依赖
pip install flask

# 启动服务
python3 app.py 5006
```

访问 http://localhost:5006

## 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | admin123 |
| 测试用户 | testuser | test1234 |

## 目录结构

```
YuQing-Forum/
├── app.py              # 主程序入口
├── forum.db            # SQLite 数据库
├── requirements.txt    # Python 依赖
├── static/             # 静态资源 (CSS, 上传文件)
└── templates/          # Jinja2 模板
```

## 版块

- 💬 日常 - 校园生活点滴
- ❤️ 表白 - 匿名表白
- 🔖 交易 - 卡牌/物品交易
- 📢 信息 - 通知公告
- 😤 吐槽 - 想说什么说什么

## 开发说明

### 数据库初始化

数据库文件为 `forum.db`，首次运行自动创建。

### 管理后台

登录后访问 `/admin`，管理员可管理：
- 用户（封禁/解禁、权限设置）
- 帖子（置顶/锁定/精华/删除）
- 版块（增删改）
- 敏感词（过滤规则）
- 操作日志

## 关于

- 作者：语晴
- 联系：yutian@utian.xyz
- 网站：https://utian.xyz

MIT License
