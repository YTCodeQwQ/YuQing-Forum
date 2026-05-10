# -*- coding: utf-8 -*-
"""二外国际论坛 — Flask 后端（含完整登录注册）"""

import os
import sqlite3
import uuid
import hashlib
from werkzeug.utils import secure_filename
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import math
from admin import admin_bp


# ==================== 等级系统 ====================

def exp_for_level(level):
    """升到 level 级需要的总EXP（level^2 * 10）"""
    return level * level * 10

def level_from_exp(exp):
    """根据总EXP计算当前等级（最高100）"""
    if exp <= 0:
        return 0
    for lv in range(1, 101):
        if exp_for_level(lv) > exp:
            return lv - 1
    return 100

def level_color(lv):
    """等级颜色：渐变从灰→蓝→紫→橙→红"""
    if lv == 100:
        return '#d93025'
    if lv >= 80:
        return '#e07a5f'
    if lv >= 60:
        return '#9b5de5'
    if lv >= 40:
        return '#457b9d'
    if lv >= 20:
        return '#2a9d8f'
    if lv >= 10:
        return '#f4a261'
    return '#888'

def level_title(lv):
    """等级称号"""
    if lv == 100:
        return '传说'
    if lv >= 90:
        return '至尊'
    if lv >= 80:
        return '大师'
    if lv >= 70:
        return '专家'
    if lv >= 60:
        return '老手'
    if lv >= 50:
        return '熟练'
    if lv >= 40:
        return '进阶'
    if lv >= 30:
        return '入门'
    if lv >= 20:
        return '新人'
    if lv >= 10:
        return '新手'
    if lv >= 1:
        return '路人'
    return '游客'

def recalc_user_exp(user_id):
    """根据用户的帖子/回复/点赞数重新计算EXP和等级"""
    conn = get_db()
    # 发帖获得EXP：每个帖子 +5 EXP
    topic_exp = conn.execute(
        "SELECT COUNT(*) * 5 FROM topics WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    # 回复获得EXP：每个回复 +2 EXP
    reply_exp = conn.execute(
        "SELECT COUNT(*) * 2 FROM replies WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    # 帖子被点赞获得EXP：每个赞 +3 EXP
    liked_topic_exp = conn.execute(
        "SELECT SUM(t.like_count) FROM topics t WHERE t.user_id = ?", (user_id,)
    ).fetchone()[0] or 0
    liked_topic_exp = int(liked_topic_exp) * 3
    # 回复被点赞获得EXP：每个赞 +1 EXP
    liked_reply_exp = conn.execute(
        "SELECT SUM(r.like_count) FROM replies r WHERE r.user_id = ?", (user_id,)
    ).fetchone()[0] or 0
    liked_reply_exp = int(liked_reply_exp) * 1
    # 粉丝获得EXP：每个粉丝 +2 EXP
    follower_exp = conn.execute(
        "SELECT COUNT(*) * 2 FROM follows WHERE following_id = ?", (user_id,)
    ).fetchone()[0]

    total_exp = topic_exp + reply_exp + liked_topic_exp + liked_reply_exp + follower_exp

    # 管理员强制 Lv100
    user = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if user and user['is_admin']:
        level = 100
    else:
        level = level_from_exp(total_exp)

    conn.execute("UPDATE users SET exp = ?, level = ? WHERE id = ?",
                 (total_exp, level, user_id))
    conn.commit()
    conn.close()
    return total_exp, level

def get_user_level_info(user_id):
    """获取用户等级详细信息"""
    conn = get_db()
    u = conn.execute("SELECT exp, level, is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not u:
        return None
    lv = u['level']
    exp = u['exp'] or 0
    cur_exp_in_level = exp - exp_for_level(lv)
    next_exp = exp_for_level(lv + 1) - exp_for_level(lv)
    return {
        'level': lv,
        'exp': exp,
        'title': level_title(lv),
        'color': level_color(lv),
        'cur_exp_in_level': cur_exp_in_level,
        'next_exp': next_exp,
        'progress': int(cur_exp_in_level / next_exp * 100) if next_exp > 0 else 100,
        'is_admin': bool(u['is_admin'])
    }

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', 'cqew-forum-secret-2026')
app.register_blueprint(admin_bp)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB 上传限制
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'forum.db')


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            color TEXT DEFAULT '#e07a5f',
            icon TEXT DEFAULT '📌',
            topic_count INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            nickname TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            avatar TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            is_admin INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # 迁移：为已存在的 users 表添加 bio 列（如果不存在）
    try:
        cur.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''")
    except:
        pass

    # 迁移：为已存在的 users 表添加 level 和 exp 列
    try:
        cur.execute("ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 0")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN exp INTEGER DEFAULT 0")
    except:
        pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            board_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            is_anonymous INTEGER DEFAULT 0,
            view_count INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0,
            reply_count INTEGER DEFAULT 0,
            is_pinned INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            is_anonymous INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic_id INTEGER,
            reply_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, topic_id),
            UNIQUE(user_id, reply_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS famous_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            added_by INTEGER NOT NULL,
            like_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
CREATE TABLE IF NOT EXISTS famous_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            famous_id INTEGER NOT NULL,
            UNIQUE(user_id, famous_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chef_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            added_by INTEGER NOT NULL,
            like_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chef_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chef_id INTEGER NOT NULL,
            UNIQUE(user_id, chef_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, topic_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER,
            to_user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # 关注关系表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS follows (
            follower_id INTEGER NOT NULL,
            following_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (follower_id, following_id)
        )
    """)

    # 用户动态表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            media_url TEXT DEFAULT '',
            media_type TEXT DEFAULT '',
            like_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # 动态点赞表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_post_likes (
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, post_id)
        )
    """)

    boards = [
        ('daily', '日常', '校园生活点滴', '#e07a5f', '💬', 1),
        ('confession', '表白', '匿名表白', '#f4a261', '❤️', 2),
        ('trade', '交易', '卡牌/物品交易', '#2a9d8f', '🔖', 3),
        ('info', '信息', '通知信息', '#457b9d', '📢', 4),
        ('tucao', '吐槽', '想说什么说什么', '#9b5de5', '😤', 5),
    ]
    for b in boards:
        cur.execute("""
            INSERT OR IGNORE INTO boards (slug, name, description, color, icon, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
        """, b)

    cur.execute("SELECT id FROM users WHERE username = 'admin'")
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO users (username, nickname, password_hash, is_admin)
            VALUES ('admin', '管理员', ?, 1)
        """, (generate_password_hash('admin123'),))

    conn.commit()
    conn.close()


def get_current_user():
    """从 session 获取当前登录用户"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    conn = get_db()
    user = conn.execute("SELECT id, username, nickname, avatar, bio, is_admin, level, exp, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


# ==================== 全局上下文 ====================
@app.context_processor
def inject_user():
    from flask import session, g
    user = get_current_user()
    return dict(user=user)

# ==================== 认证路由 ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('请输入用户名和密码', 'error')
            return redirect(url_for('login'))

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['nickname'] = user['nickname']
            session['is_admin'] = user['is_admin']
            flash('登录成功', 'success')
            # 登录时重新计算等级
            recalc_user_exp(user['id'])
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        nickname = request.form.get('nickname', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        if not username or not nickname or not password:
            flash('所有字段都不能为空', 'error')
            return redirect(url_for('register'))

        if len(username) < 3 or len(username) > 20:
            flash('用户名长度需在3-20字符之间', 'error')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('密码至少6位', 'error')
            return redirect(url_for('register'))

        if password != password2:
            flash('两次密码不一致', 'error')
            return redirect(url_for('register'))

        conn = get_db()
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            conn.close()
            flash('用户名已被占用', 'error')
            return redirect(url_for('register'))

        password_hash = generate_password_hash(password)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (username, nickname, password_hash)
            VALUES (?, ?, ?)
        """, (username, nickname, password_hash))
        user_id = cur.lastrowid
        conn.commit()
        conn.close()

        session['user_id'] = user_id
        session['nickname'] = nickname
        flash('注册成功，欢迎 ' + nickname, 'success')
        # 注册时初始化等级
        recalc_user_exp(user_id)
        return redirect(url_for('index'))

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录', 'info')
    return redirect(url_for('index'))


@app.route('/profile')
def profile():
    user = get_current_user()
    if not user:
        flash('请先登录', 'error')
        return redirect(url_for('login'))

    conn = get_db()
    topics = conn.execute("""
        SELECT t.*, b.name as board_name, b.color as board_color, b.icon as board_icon
        FROM topics t
        LEFT JOIN boards b ON t.board_id = b.id
        WHERE t.user_id = ?
        ORDER BY t.created_at DESC
        LIMIT 50
    """, (user['id'],)).fetchall()
    topic_count = len(topics)
    reply_count = conn.execute("SELECT COUNT(*) FROM replies WHERE user_id = ?", (user['id'],)).fetchone()[0]
    like_count = conn.execute("SELECT COUNT(*) FROM likes WHERE user_id = ?", (user['id'],)).fetchone()[0]
    conn.close()

    stats = {'topics': topic_count, 'replies': reply_count, 'likes': like_count}
    return render_template('profile.html', user=user, topics=topics, stats=stats)


# ==================== 页面路由 ====================

@app.route('/')
def index():
    user = get_current_user()
    conn = get_db()
    cur = conn.cursor()

    boards = cur.execute("SELECT * FROM boards ORDER BY sort_order").fetchall()

    topics = cur.execute("""
        SELECT t.*, b.name as board_name, b.color as board_color, b.icon as board_icon,
               u.nickname as author_nickname, u.is_admin as author_is_admin, u.level as author_level
        FROM topics t
        LEFT JOIN boards b ON t.board_id = b.id
        LEFT JOIN users u ON t.user_id = u.id
        ORDER BY t.is_pinned DESC, t.created_at DESC
        LIMIT 30
    """).fetchall()

    hot_topics = cur.execute("""
        SELECT t.*, b.name as board_name, b.color as board_color, b.icon as board_icon,
               u.nickname as author_nickname,
               (t.view_count + t.like_count * 3) as hot_score
        FROM topics t
        LEFT JOIN boards b ON t.board_id = b.id
        LEFT JOIN users u ON t.user_id = u.id
        WHERE t.created_at >= datetime('now', '-7 days')
        ORDER BY hot_score DESC
        LIMIT 5
    """).fetchall()

    online_count = cur.execute("""
        SELECT COUNT(DISTINCT user_id) FROM replies
        WHERE created_at >= datetime('now', '-1 hour')
    """).fetchone()[0] or 8

    conn.close()
    return render_template('index.html', boards=list(boards), topics=list(topics),
                           hot_topics=list(hot_topics), online_count=online_count,
                           user=user)


@app.route('/board/<slug>')
def board_page(slug):
    user = get_current_user()
    conn = get_db()
    cur = conn.cursor()

    board = cur.execute("SELECT * FROM boards WHERE slug = ?", (slug,)).fetchone()
    if not board:
        conn.close()
        return "版块不存在", 404

    topics = cur.execute("""
        SELECT t.*, u.nickname as author_nickname, u.avatar as author_avatar, u.is_admin as author_is_admin, u.level as author_level
        FROM topics t
        LEFT JOIN users u ON t.user_id = u.id
        WHERE t.board_id = ?
        ORDER BY t.is_pinned DESC, t.created_at DESC
        LIMIT 50
    """, (board['id'],)).fetchall()

    conn.close()
    return render_template('board.html', board=dict(board), topics=list(topics), user=user)


@app.route('/topic/<int:tid>')
def topic_page(tid):
    user = get_current_user()
    conn = get_db()
    cur = conn.cursor()

    cur.execute("UPDATE topics SET view_count = view_count + 1 WHERE id = ?", (tid,))
    conn.commit()

    topic = cur.execute("""
        SELECT t.*, b.name as board_name, b.color as board_color, b.icon as board_icon,
               b.slug as board_slug, u.nickname as author_nickname, u.avatar as author_avatar, u.is_admin as author_is_admin, u.level as author_level
        FROM topics t
        LEFT JOIN boards b ON t.board_id = b.id
        LEFT JOIN users u ON t.user_id = u.id
        WHERE t.id = ?
    """, (tid,)).fetchone()

    if not topic:
        conn.close()
        return "主题不存在", 404

    replies = cur.execute("""
        SELECT r.*, u.nickname as author_nickname, u.avatar as author_avatar, u.is_admin as author_is_admin, u.level as author_level
        FROM replies r
        LEFT JOIN users u ON r.user_id = u.id
        WHERE r.topic_id = ?
        ORDER BY r.created_at DESC
    """, (tid,)).fetchall()

    # 检查当前用户是否点赞
    liked_topics = []
    liked_replies = []
    if user:
        liked_topics = [r['topic_id'] for r in conn.execute(
            "SELECT topic_id FROM likes WHERE user_id = ? AND topic_id IS NOT NULL", (user['id'],)
        ).fetchall()]
        liked_replies = [r['reply_id'] for r in conn.execute(
            "SELECT reply_id FROM likes WHERE user_id = ? AND reply_id IS NOT NULL", (user['id'],)
        ).fetchall()]

    conn.close()
    return render_template('topic.html', topic=dict(topic), replies=list(replies),
                           user=user, liked_topics=liked_topics, liked_replies=liked_replies)


@app.route('/new/<slug>')
def new_topic_page(slug):
    user = get_current_user()
    if not user:
        flash('请先登录', 'error')
        return redirect(url_for('login'))

    conn = get_db()
    board = conn.execute("SELECT * FROM boards WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    if not board:
        return "版块不存在", 404
    return render_template('new_topic.html', board=dict(board), user=user)


# ==================== API 路由 ====================

@app.route('/api/boards')
def api_boards():
    conn = get_db()
    boards = conn.execute("SELECT * FROM boards ORDER BY sort_order").fetchall()
    conn.close()
    return jsonify([dict(b) for b in boards])


@app.route('/api/topics')
def api_topics():
    conn = get_db()
    board_id = request.args.get('board_id', type=int)
    if board_id:
        topics = conn.execute("""
            SELECT t.*, b.name as board_name, b.color as board_color,
                   u.nickname as author_nickname
            FROM topics t
            LEFT JOIN boards b ON t.board_id = b.id
            LEFT JOIN users u ON t.user_id = u.id
            WHERE t.board_id = ?
            ORDER BY t.is_pinned DESC, t.created_at DESC
        """, (board_id,)).fetchall()
    else:
        topics = conn.execute("""
            SELECT t.*, b.name as board_name, b.color as board_color,
                   u.nickname as author_nickname
            FROM topics t
            LEFT JOIN boards b ON t.board_id = b.id
            LEFT JOIN users u ON t.user_id = u.id
            ORDER BY t.is_pinned DESC, t.created_at DESC
            LIMIT 30
        """).fetchall()
    conn.close()
    return jsonify([dict(t) for t in topics])


@app.route('/api/topic', methods=['POST'])
def api_create_topic():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    title = data.get('title', '').strip()
    content = data.get('content', '').strip()
    board_id = data.get('board_id')
    try:
        if board_id is not None:
            board_id = int(board_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'board_id 必须是有效整数'}), 400
    is_anonymous = 1 if str(data.get('is_anonymous', '0')) == '1' else 0

    if not title or not content or not board_id:
        return jsonify({'error': '缺少必要字段'}), 400

    # 验证 board_id 对应的版块存在
    conn = get_db()
    board = conn.execute("SELECT id FROM boards WHERE id = ?", (board_id,)).fetchone()
    conn.close()
    if not board:
        return jsonify({'error': '版块不存在'}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO topics (title, content, board_id, user_id, is_anonymous)
        VALUES (?, ?, ?, ?, ?)
    """, (title, content, board_id, user['id'], is_anonymous))
    topic_id = cur.lastrowid
    cur.execute("UPDATE boards SET topic_count = topic_count + 1 WHERE id = ?", (board_id,))
    conn.commit()
    # 更新用户EXP和等级
    recalc_user_exp(user['id'])
    conn.close()
    return jsonify({'success': True, 'topic_id': topic_id})


@app.route('/api/reply', methods=['POST'])
def api_create_reply():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    topic_id = data.get('topic_id')
    try:
        if topic_id is not None:
            topic_id = int(topic_id)
    except (ValueError, TypeError):
        return jsonify({'error': 'topic_id 必须是有效整数'}), 400
    content = data.get('content', '').strip()
    is_anonymous = 1 if str(data.get('is_anonymous', '0')) == '1' else 0
    media_url = data.get('media_url', '').strip()[:500]
    media_type = data.get('media_type', '').strip()[:10]

    if not content or not topic_id:
        return jsonify({'error': '缺少必要字段'}), 400

    # 验证 topic 存在
    conn = get_db()
    topic = conn.execute("SELECT id FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if not topic:
        conn.close()
        return jsonify({'error': '帖子不存在'}), 400

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO replies (topic_id, user_id, content, is_anonymous, media_url, media_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (topic_id, user['id'], content, is_anonymous, media_url, media_type))
    reply_id = cur.lastrowid
    cur.execute("UPDATE topics SET reply_count = reply_count + 1, updated_at = datetime('now') WHERE id = ?", (topic_id,))
    conn.commit()
    # 更新用户EXP和等级
    recalc_user_exp(user['id'])
    conn.close()
    return jsonify({'success': True, 'reply_id': reply_id})

@app.route('/api/like', methods=['POST'])
def api_like():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    topic_id = data.get('topic_id')
    reply_id = data.get('reply_id')
    if topic_id is not None:
        topic_id = int(topic_id)
    if reply_id is not None:
        reply_id = int(reply_id)

    conn = get_db()
    cur = conn.cursor()
    exp_update_user_ids = []  # 记录需要更新EXP的用户ID

    try:
        if topic_id:
            cur.execute("INSERT INTO likes (user_id, topic_id) VALUES (?, ?)", (user['id'], topic_id))
            cur.execute("UPDATE topics SET like_count = like_count + 1 WHERE id = ?", (topic_id,))
            # 获取帖子作者ID并记录
            author = cur.execute("SELECT user_id FROM topics WHERE id = ?", (topic_id,)).fetchone()
            if author:
                exp_update_user_ids.append(author[0])
        elif reply_id:
            cur.execute("INSERT INTO likes (user_id, reply_id) VALUES (?, ?)", (user['id'], reply_id))
            cur.execute("UPDATE replies SET like_count = like_count + 1 WHERE id = ?", (reply_id,))
            # 获取回复作者ID并记录
            author = cur.execute("SELECT user_id FROM replies WHERE id = ?", (reply_id,)).fetchone()
            if author:
                exp_update_user_ids.append(author[0])
        conn.commit()
        liked = True
    except sqlite3.IntegrityError:
        if topic_id:
            cur.execute("DELETE FROM likes WHERE user_id = ? AND topic_id = ?", (user['id'], topic_id))
            cur.execute("UPDATE topics SET like_count = MAX(0, like_count - 1) WHERE id = ?", (topic_id,))
            author = cur.execute("SELECT user_id FROM topics WHERE id = ?", (topic_id,)).fetchone()
            if author:
                exp_update_user_ids.append(author[0])
        elif reply_id:
            cur.execute("DELETE FROM likes WHERE user_id = ? AND reply_id = ?", (user['id'], reply_id))
            cur.execute("UPDATE replies SET like_count = MAX(0, like_count - 1) WHERE id = ?", (reply_id,))
            author = cur.execute("SELECT user_id FROM replies WHERE id = ?", (reply_id,)).fetchone()
            if author:
                exp_update_user_ids.append(author[0])
        conn.commit()
        liked = False

    conn.close()

    # 在事务提交后再更新EXP（避免嵌套连接锁）
    for uid in exp_update_user_ids:
        recalc_user_exp(uid)

    return jsonify({'success': True, 'liked': liked})


# ==================== 风云人物榜 ====================

@app.route('/famous')
def famous_page():
    user = get_current_user()
    conn = get_db()

    famous_list = [dict(row) for row in conn.execute("""
        SELECT f.*, u.nickname as adder_name
        FROM famous_users f
        LEFT JOIN users u ON f.added_by = u.id
        ORDER BY f.like_count DESC, f.number ASC
    """).fetchall()]

    # check if current user liked each
    liked_ids = []
    if user:
        liked = conn.execute("SELECT famous_id FROM famous_likes WHERE user_id = ?", (user['id'],)).fetchall()
        liked_ids = [r['famous_id'] for r in liked]

    # pre-load comments for all famous users
    all_comments = {}
    for row in conn.execute("""
        SELECT c.famous_id, c.content, c.created_at, u.nickname as commenter_name
        FROM famous_comments c LEFT JOIN users u ON c.user_id = u.id
        ORDER BY c.created_at DESC
    """).fetchall():
        cid = row['famous_id']
        if cid not in all_comments:
            all_comments[cid] = []
        all_comments[cid].append(dict(row))

    conn.close()
    return render_template('famous.html',
                           famous_list=list(famous_list),
                           liked_ids=liked_ids,
                           user=user,
                           all_comments=all_comments)


@app.route('/famous/add')
def famous_add_page():
    user = get_current_user()
    if not user:
        return redirect('/login?next=/famous/add')
    return render_template('famous_add.html', user=user)


@app.route('/api/famous/add', methods=['POST'])
def api_famous_add():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    image_url = data.get('image_url', '').strip()

    if not name:
        return jsonify({'error': '姓名不能为空'}), 400

    description = description[:300]
    image_url = image_url[:500]

    conn = get_db()
    cur = conn.cursor()

    # auto number
    max_num = conn.execute("SELECT MAX(number) as m FROM famous_users").fetchone()['m'] or 0
    number = max_num + 1

    cur.execute("""
        INSERT INTO famous_users (number, name, description, image_url, added_by)
        VALUES (?, ?, ?, ?, ?)
    """, (number, name, description, image_url, user['id']))

    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/famous/like', methods=['POST'])
def api_famous_like():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    famous_id = int(data.get('famous_id'))

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO famous_likes (user_id, famous_id) VALUES (?, ?)", (user['id'], famous_id))
        cur.execute("UPDATE famous_users SET like_count = like_count + 1 WHERE id = ?", (famous_id,))
        conn.commit()
        liked = True
    except sqlite3.IntegrityError:
        cur.execute("DELETE FROM famous_likes WHERE user_id = ? AND famous_id = ?", (user['id'], famous_id))
        cur.execute("UPDATE famous_users SET like_count = MAX(0, like_count - 1) WHERE id = ?", (famous_id,))
        conn.commit()
        liked = False
    conn.close()
    return jsonify({'success': True, 'liked': liked})


@app.route('/api/famous/delete', methods=['POST'])
def api_famous_delete():
    user = get_current_user()
    if not user or not user.get('is_admin'):
        return jsonify({'error': '无权限'}), 403

    data = request.get_json()
    famous_id = int(data.get('famous_id'))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM famous_likes WHERE famous_id = ?", (famous_id,))
    cur.execute("DELETE FROM famous_users WHERE id = ?", (famous_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== API: 删除自己的帖子 ====================
@app.route('/api/topic/delete', methods=['POST'])
def api_delete_topic():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json()
    topic_id = data.get('topic_id')
    conn = get_db()
    topic = conn.execute("SELECT user_id FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if not topic:
        conn.close()
        return jsonify({'success': False, 'error': '帖子不存在'})
    if topic['user_id'] != user['id'] and not user.get('is_admin'):
        conn.close()
        return jsonify({'success': False, 'error': '无权删除'})
    conn.execute("DELETE FROM replies WHERE topic_id = ?", (topic_id,))
    conn.execute("DELETE FROM likes WHERE topic_id = ?", (topic_id,))
    conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== API: 编辑自己的帖子 ====================
@app.route('/api/topic/edit', methods=['POST'])
def api_edit_topic():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json()
    topic_id = data.get('topic_id')
    new_content = data.get('content', '').strip()
    new_title = data.get('title', '').strip()
    if not new_content:
        return jsonify({'success': False, 'error': '内容不能为空'})
    conn = get_db()
    topic = conn.execute("SELECT user_id FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if not topic:
        conn.close()
        return jsonify({'success': False, 'error': '帖子不存在'})
    if topic['user_id'] != user['id']:
        conn.close()
        return jsonify({'success': False, 'error': '无权编辑'})
    if new_title:
        conn.execute("UPDATE topics SET title=?, content=?, updated_at=datetime('now') WHERE id=?", (new_title, new_content, topic_id))
    else:
        conn.execute("UPDATE topics SET content=?, updated_at=datetime('now') WHERE id=?", (new_content, topic_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== API: 删除自己的回复 ====================
@app.route('/api/reply/delete', methods=['POST'])
def api_delete_reply():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json()
    reply_id = data.get('reply_id')
    conn = get_db()
    reply = conn.execute("SELECT user_id, topic_id FROM replies WHERE id = ?", (reply_id,)).fetchone()
    if not reply:
        conn.close()
        return jsonify({'success': False, 'error': '回复不存在'})
    if reply['user_id'] != user['id'] and not user.get('is_admin'):
        conn.close()
        return jsonify({'success': False, 'error': '无权删除'})
    conn.execute("DELETE FROM replies WHERE id = ?", (reply_id,))
    conn.execute("UPDATE topics SET reply_count = MAX(0, reply_count - 1) WHERE id = ?", (reply['topic_id'],))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== API: 编辑自己的回复 ====================
@app.route('/api/reply/edit', methods=['POST'])
def api_edit_reply():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json()
    reply_id = data.get('reply_id')
    new_content = data.get('content', '').strip()
    if not new_content:
        return jsonify({'success': False, 'error': '内容不能为空'})
    conn = get_db()
    reply = conn.execute("SELECT user_id FROM replies WHERE id = ?", (reply_id,)).fetchone()
    if not reply:
        conn.close()
        return jsonify({'success': False, 'error': '回复不存在'})
    if reply['user_id'] != user['id']:
        conn.close()
        return jsonify({'success': False, 'error': '无权编辑'})
    conn.execute("UPDATE replies SET content=?, updated_at=datetime('now') WHERE id=?", (new_content, reply_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


import re
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'mp4', 'mov', 'webm', 'avi', 'mkv'}
ALLOWED_VIDEO = {'mp4', 'mov', 'webm', 'avi', 'mkv'}
ALLOWED_IMAGE = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}

def is_valid_username(username):
    """验证用户名：只能包含字母、数字、下划线，不允许空格和特殊字符"""
    if not username or len(username) < 3 or len(username) > 20:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', username))


@app.route('/api/famous/upload', methods=['POST'])
def api_famous_upload():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_IMAGE:
        return jsonify({'error': '不支持的图片格式，支持：'+', '.join(ALLOWED_IMAGE)}), 400

    upload_dir = os.path.join(BASE_DIR, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)

    filename = secure_filename(f"{uuid.uuid4().hex}.{ext}")
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    return jsonify({'url': f'/static/uploads/{filename}'})


@app.route('/api/upload', methods=['POST'])
def api_upload():
    """通用上传接口，支持图片和视频，返回 url 和 media_type"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': '不支持的格式，支持：'+', '.join(ALLOWED_EXTENSIONS)}), 400

    upload_dir = os.path.join(BASE_DIR, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)

    filename = secure_filename(f"{uuid.uuid4().hex}.{ext}")
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    media_type = 'video' if ext in ALLOWED_VIDEO else 'image'
    return jsonify({'url': f'/static/uploads/{filename}', 'media_type': media_type})


# ==================== 厨神争霸榜 ====================

@app.route('/chef')
def chef_page():
    user = get_current_user()
    conn = get_db()

    chef_list = [dict(row) for row in conn.execute("""
        SELECT c.*, u.nickname as adder_name
        FROM chef_users c
        LEFT JOIN users u ON c.added_by = u.id
        ORDER BY c.like_count DESC, c.number ASC
    """).fetchall()]

    liked_ids = []
    if user:
        liked = conn.execute("SELECT chef_id FROM chef_likes WHERE user_id = ?", (user['id'],)).fetchall()
        liked_ids = [r['chef_id'] for r in liked]

    all_comments = {}
    for row in conn.execute("""
        SELECT c.chef_id, c.content, c.created_at, u.nickname as commenter_name
        FROM chef_comments c LEFT JOIN users u ON c.user_id = u.id
        ORDER BY c.created_at DESC
    """).fetchall():
        cid = row['chef_id']
        if cid not in all_comments:
            all_comments[cid] = []
        all_comments[cid].append(dict(row))

    conn.close()
    return render_template('chef.html',
                           chef_list=chef_list,
                           liked_ids=liked_ids,
                           user=user,
                           all_comments=all_comments)


@app.route('/chef/add')
def chef_add_page():
    user = get_current_user()
    if not user:
        return redirect('/login?next=/chef/add')
    return render_template('chef_add.html', user=user)


@app.route('/api/chef/add', methods=['POST'])
def api_chef_add():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    image_url = data.get('image_url', '').strip()

    if not name:
        return jsonify({'error': '姓名不能为空'}), 400

    description = description[:300]
    image_url = image_url[:500]

    conn = get_db()
    max_num = conn.execute("SELECT MAX(number) as m FROM chef_users").fetchone()['m'] or 0
    conn.execute("""
        INSERT INTO chef_users (number, name, description, image_url, added_by)
        VALUES (?, ?, ?, ?, ?)
    """, (max_num + 1, name, description, image_url, user['id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/chef/like', methods=['POST'])
def api_chef_like():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    chef_id = int(data.get('chef_id'))

    conn = get_db()
    try:
        conn.execute("INSERT INTO chef_likes (user_id, chef_id) VALUES (?, ?)", (user['id'], chef_id))
        conn.execute("UPDATE chef_users SET like_count = like_count + 1 WHERE id = ?", (chef_id,))
        conn.commit()
        liked = True
    except sqlite3.IntegrityError:
        conn.execute("DELETE FROM chef_likes WHERE user_id = ? AND chef_id = ?", (user['id'], chef_id))
        conn.execute("UPDATE chef_users SET like_count = MAX(0, like_count - 1) WHERE id = ?", (chef_id,))
        conn.commit()
        liked = False
    conn.close()
    return jsonify({'success': True, 'liked': liked})


@app.route('/api/chef/delete', methods=['POST'])
def api_chef_delete():
    user = get_current_user()
    if not user or not user.get('is_admin'):
        return jsonify({'error': '无权限'}), 403

    data = request.get_json()
    chef_id = int(data.get('chef_id'))

    conn = get_db()
    conn.execute("DELETE FROM chef_likes WHERE chef_id = ?", (chef_id,))
    conn.execute("DELETE FROM chef_users WHERE id = ?", (chef_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/chef/upload', methods=['POST'])
def api_chef_upload():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_IMAGE:
        return jsonify({'error': '不支持的图片格式，支持：'+', '.join(ALLOWED_IMAGE)}), 400

    upload_dir = os.path.join(BASE_DIR, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)

    filename = secure_filename(f"{uuid.uuid4().hex}.jpg")
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    return jsonify({'url': f'/static/uploads/{filename}'})


@app.route('/api/upload-test', methods=['POST'])
def api_upload_test():
    """诊断上传问题"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    if 'file' not in request.files:
        return jsonify({'error': 'no file in request', 'files': list(request.files.keys())}), 400
    file = request.files['file']
    file.seek(0, 2)  # seek to end
    size = file.tell()
    file.seek(0)  # reset
    return jsonify({
        'filename': file.filename,
        'size': size,
        'content_type': file.content_type
    })


# ==================== 风云人物评论 ====================

@app.route('/api/famous/comments/<int:famous_id>')
def api_famous_comments(famous_id):
    conn = get_db()
    comments = [dict(row) for row in conn.execute("""
        SELECT c.*, u.nickname as commenter_name
        FROM famous_comments c
        LEFT JOIN users u ON c.user_id = u.id
        WHERE c.famous_id = ?
        ORDER BY c.created_at DESC
    """, (famous_id,)).fetchall()]
    conn.close()
    return jsonify({'success': True, 'comments': comments})


@app.route('/api/famous/comment', methods=['POST'])
def api_famous_comment():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    famous_id = int(data.get('famous_id'))
    content = data.get('content', '').strip()
    media_url = data.get('media_url', '').strip()[:500]
    media_type = data.get('media_type', '').strip()[:10]

    if not content and not media_url:
        return jsonify({'error': '内容或媒体不能为空'}), 400
    if len(content) > 300:
        return jsonify({'error': '内容太长了'}), 400

    conn = get_db()
    conn.execute("""
        INSERT INTO famous_comments (famous_id, user_id, content, media_url, media_type)
        VALUES (?, ?, ?, ?, ?)
    """, (famous_id, user['id'], content, media_url, media_type))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== 厨神争霸评论 ====================

@app.route('/api/chef/comments/<int:chef_id>')
def api_chef_comments(chef_id):
    conn = get_db()
    comments = [dict(row) for row in conn.execute("""
        SELECT c.*, u.nickname as commenter_name
        FROM chef_comments c
        LEFT JOIN users u ON c.user_id = u.id
        WHERE c.chef_id = ?
        ORDER BY c.created_at DESC
    """, (chef_id,)).fetchall()]
    conn.close()
    return jsonify({'success': True, 'comments': comments})


@app.route('/api/chef/comment', methods=['POST'])
def api_chef_comment():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    chef_id = int(data.get('chef_id'))
    content = data.get('content', '').strip()
    media_url = data.get('media_url', '').strip()[:500]
    media_type = data.get('media_type', '').strip()[:10]

    if not content and not media_url:
        return jsonify({'error': '内容或媒体不能为空'}), 400
    if len(content) > 300:
        return jsonify({'error': '内容太长了'}), 400

    conn = get_db()
    conn.execute("""
        INSERT INTO chef_comments (chef_id, user_id, content, media_url, media_type)
        VALUES (?, ?, ?, ?, ?)
    """, (chef_id, user['id'], content, media_url, media_type))
    conn.commit()
    conn.close()
    return jsonify({'success': True})



# ==================== API: 编辑排行榜评论 ====================
@app.route('/api/famous/comment/edit', methods=['POST'])
def api_famous_comment_edit():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json()
    comment_id = data.get('comment_id')
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'success': False, 'error': '内容不能为空'})
    conn = get_db()
    comment = conn.execute("SELECT user_id FROM famous_comments WHERE id = ?", (comment_id,)).fetchone()
    if not comment:
        conn.close()
        return jsonify({'success': False, 'error': '评论不存在'})
    if comment['user_id'] != user['id']:
        conn.close()
        return jsonify({'success': False, 'error': '无权编辑'})
    conn.execute("UPDATE famous_comments SET content=? WHERE id=?", (content, comment_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/chef/comment/edit', methods=['POST'])
def api_chef_comment_edit():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json()
    comment_id = data.get('comment_id')
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'success': False, 'error': '内容不能为空'})
    conn = get_db()
    comment = conn.execute("SELECT user_id FROM chef_comments WHERE id = ?", (comment_id,)).fetchone()
    if not comment:
        conn.close()
        return jsonify({'success': False, 'error': '评论不存在'})
    if comment['user_id'] != user['id']:
        conn.close()
        return jsonify({'success': False, 'error': '无权编辑'})
    conn.execute("UPDATE chef_comments SET content=? WHERE id=?", (content, comment_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== API: 登录 ====================
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'success': False, 'error': '用户名和密码不能为空'})

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'success': False, 'error': '用户名或密码错误'})

    session['user_id'] = user['id']
    session['nickname'] = user['nickname']
    session['is_admin'] = user['is_admin']
    return jsonify({'success': True, 'location': '/'})


# ==================== API: 注册 ====================
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = data.get('username', '').strip()
    nickname = data.get('nickname', '').strip()
    password = data.get('password', '')

    if not username or not nickname or not password:
        return jsonify({'success': False, 'error': '所有字段都不能为空'})
    if len(username) < 3 or len(username) > 20:
        return jsonify({'success': False, 'error': '用户名长度需在3-20字符之间'})
    if not is_valid_username(username):
        return jsonify({'success': False, 'error': '用户名只能包含字母、数字、下划线'})
    if len(password) < 6:
        return jsonify({'success': False, 'error': '密码至少6位'})

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'error': '用户名已被占用'})

    # 检查是否第一个用户，第一个用户设为管理员且Lv100
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    is_first_user = (user_count == 0)

    password_hash = generate_password_hash(password)
    if is_first_user:
        user_id = conn.execute(
            "INSERT INTO users (username, nickname, password_hash, is_admin, level, exp) VALUES (?, ?, ?, 1, 100, 0)",
            (username, nickname, password_hash)
        ).lastrowid
    else:
        user_id = conn.execute(
            "INSERT INTO users (username, nickname, password_hash) VALUES (?, ?, ?)",
            (username, nickname, password_hash)
        ).lastrowid
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== Settings 页面 ====================
@app.route('/settings')
def settings_page():
    user = get_current_user()
    if not user:
        flash('请先登录', 'error')
        return redirect(url_for('login'))
    return render_template('settings.html', user=user)


@app.route('/api/profile', methods=['POST'])
def api_update_profile():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': '请先登录'}), 401

    data = request.get_json()
    nickname = data.get('nickname', '').strip()
    avatar = data.get('avatar', '').strip()[:500]
    bio = data.get('bio', '').strip()[:200]

    if not nickname:
        return jsonify({'success': False, 'error': '昵称不能为空'})

    conn = get_db()
    conn.execute("UPDATE users SET nickname = ?, avatar = ?, bio = ? WHERE id = ?",
                 (nickname, avatar, bio, user['id']))
    session['nickname'] = nickname
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/password', methods=['POST'])
def api_change_password():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': '请先登录'}), 401

    data = request.get_json()
    old_pw = data.get('old_password', '')
    new_pw = data.get('new_password', '')

    if len(new_pw) < 6:
        return jsonify({'success': False, 'error': '新密码至少6位'})

    conn = get_db()
    db_user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user['id'],)).fetchone()
    if not db_user or not check_password_hash(db_user['password_hash'], old_pw):
        conn.close()
        return jsonify({'success': False, 'error': '原密码错误'})

    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                 (generate_password_hash(new_pw), user['id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== Admin 页面 ====================
@app.route('/admin')
def admin_page():
    user = get_current_user()
    if not user or not user.get('is_admin'):
        flash('无权限访问', 'error')
        return redirect(url_for('index'))

    conn = get_db()
    famous = conn.execute("SELECT * FROM famous_users ORDER BY number").fetchall()
    chef = conn.execute("SELECT * FROM chef_users ORDER BY number").fetchall()
    boards = conn.execute("SELECT * FROM boards ORDER BY sort_order").fetchall()
    users = conn.execute("SELECT id, username, nickname, bio, is_admin, created_at, level, exp FROM users ORDER BY id").fetchall()
    topics = conn.execute("""
        SELECT t.id, t.title, t.like_count, t.reply_count, t.user_id
        FROM topics t
        ORDER BY t.id DESC LIMIT 100
    """).fetchall()
    tags = conn.execute('SELECT id, name, color, created_at FROM tags ORDER BY id').fetchall()
    tag_counts = {}
    for t in tags:
        count = conn.execute('SELECT COUNT(*) FROM user_tags WHERE tag_id = ?', (t[0],)).fetchone()[0]
        tag_counts[t[0]] = count
    # user_tags: {user_id: [tag_id, ...]}
    user_tags = {}
    for row in conn.execute('SELECT user_id, tag_id FROM user_tags').fetchall():
        uid, tid = row
        if uid not in user_tags:
            user_tags[uid] = []
        user_tags[uid].append(tid)
    conn.close()
    return render_template('admin.html', user=user, famous=list(famous), chef=list(chef),
                           boards=list(boards), users=list(users), topics=list(topics),
                           tags=list(tags), tag_counts=tag_counts, user_tags=user_tags)


# ==================== 搜索功能 ====================
@app.route('/search')
def search_page():
    user = get_current_user()
    q = request.args.get('q', '').strip()
    results = []
    if q:
        conn = get_db()
        cur = conn.cursor()
        # 只搜索 topic id（编号）
        try:
            topic_id = int(q)
        except ValueError:
            topics = []
        else:
            topics = cur.execute("""
                SELECT t.*, b.name as board_name, b.slug as board_slug,
                       u.nickname as author_nickname, u.avatar as author_avatar
                FROM topics t
                LEFT JOIN boards b ON t.board_id = b.id
                LEFT JOIN users u ON t.user_id = u.id
                WHERE t.id = ?
                ORDER BY t.created_at DESC
            """, (topic_id,)).fetchall()
        results = list(topics)
        conn.close()
    return render_template('search.html', user=user, q=q, results=results)


@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'success': True, 'results': []})

    conn = get_db()
    try:
        topic_id = int(q)
    except ValueError:
        topics = []
    else:
        topics = conn.execute("""
            SELECT t.*, b.name as board_name, b.slug as board_slug,
                   u.nickname as author_nickname
            FROM topics t
            LEFT JOIN boards b ON t.board_id = b.id
            LEFT JOIN users u ON t.user_id = u.id
            WHERE t.id = ?
            ORDER BY t.created_at DESC
            LIMIT 30
        """, (topic_id,)).fetchall()
    conn.close()
    return jsonify({'success': True, 'results': [dict(t) for t in topics]})


# ==================== API: 用户信息 ====================
@app.route('/api/user/me')
def api_user_me():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    return jsonify({
        'success': True,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'nickname': user['nickname'],
            'avatar': user.get('avatar', ''),
            'bio': user.get('bio', ''),
            'is_admin': user.get('is_admin', 0),
            'created_at': user.get('created_at', '')
        }
    })


@app.route('/api/user/avatar', methods=['POST'])
def api_user_avatar():
    """支持两种方式：1) JSON {avatar_url: "..."}  2) multipart/form-data 上传图片文件"""
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    avatar_url = ''
    # 方式1：URL
    if request.is_json:
        data = request.get_json()
        avatar_url = (data.get('avatar_url') or '').strip()
    else:
        # 方式2：文件上传，转存到 static/uploads/
        file = request.files.get('avatar')
        if file and file.filename:
            from werkzeug.utils import secure_filename
            import os, uuid, hashlib
            ext = file.filename.rsplit('.', 1)[-1].lower()
            if ext not in {'png','jpg','jpeg','gif','webp','bmp'}:
                return jsonify({'error': '不支持的图片格式'}), 400
            # 保存到 static/uploads/
            upload_dir = os.path.join('static', 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            filename = hashlib.md5((str(uuid.uuid4()) + file.filename).encode()).hexdigest()[:16] + '.' + ext
            filepath = os.path.join(upload_dir, filename)
            file.save(filepath)
            avatar_url = '/' + filepath
        else:
            return jsonify({'error': '未提供头像'}), 400

    if avatar_url:
        conn = get_db()
        conn.execute("UPDATE users SET avatar=? WHERE id=?", (avatar_url, user['id']))
        conn.commit()
        conn.close()
    return jsonify({'success': True, 'avatar_url': avatar_url})


# ==================== API: 帖子回复列表 ====================
@app.route('/api/topic/<int:tid>/replies')
def api_topic_replies(tid):
    conn = get_db()
    topic = conn.execute("SELECT id FROM topics WHERE id = ?", (tid,)).fetchone()
    if not topic:
        conn.close()
        return jsonify({'error': '帖子不存在'}), 404

    replies = conn.execute("""
        SELECT r.*, u.nickname as author_nickname, u.avatar as author_avatar, u.is_admin as author_is_admin, u.level as author_level
        FROM replies r
        LEFT JOIN users u ON r.user_id = u.id
        WHERE r.topic_id = ?
        ORDER BY r.created_at DESC
    """, (tid,)).fetchall()
    conn.close()
    return jsonify({'success': True, 'replies': [dict(r) for r in replies]})


# ==================== API: 版块帖子列表（按slug） ====================
@app.route('/api/board/<slug>/topics')
def api_board_topics(slug):
    conn = get_db()
    board = conn.execute("SELECT * FROM boards WHERE slug = ?", (slug,)).fetchone()
    if not board:
        conn.close()
        return jsonify({'error': '版块不存在'}), 404

    topics = conn.execute("""
        SELECT t.*, u.nickname as author_nickname, u.is_admin as author_is_admin, u.level as author_level
        FROM topics t
        LEFT JOIN users u ON t.user_id = u.id
        WHERE t.board_id = ?
        ORDER BY t.is_pinned DESC, t.created_at DESC
    """, (board['id'],)).fetchall()
    conn.close()
    return jsonify({'success': True, 'board': dict(board), 'topics': [dict(t) for t in topics]})


# ==================== API: 收藏功能 ====================
@app.route('/api/favorite/topic/<int:tid>', methods=['POST'])
def api_favorite_topic(tid):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    conn = get_db()
    topic = conn.execute("SELECT id FROM topics WHERE id = ?", (tid,)).fetchone()
    if not topic:
        conn.close()
        return jsonify({'error': '帖子不存在'}), 404

    try:
        conn.execute("INSERT INTO favorites (user_id, topic_id) VALUES (?, ?)", (user['id'], tid))
        conn.commit()
        favorited = True
    except sqlite3.IntegrityError:
        conn.execute("DELETE FROM favorites WHERE user_id = ? AND topic_id = ?", (user['id'], tid))
        conn.commit()
        favorited = False
    conn.close()
    return jsonify({'success': True, 'favorited': favorited})


@app.route('/api/favorites')
def api_my_favorites():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    conn = get_db()
    favorites = conn.execute("""
        SELECT t.*, b.name as board_name, b.slug as board_slug,
               u.nickname as author_nickname
        FROM favorites f
        JOIN topics t ON f.topic_id = t.id
        LEFT JOIN boards b ON t.board_id = b.id
        LEFT JOIN users u ON t.user_id = u.id
        WHERE f.user_id = ?
        ORDER BY f.created_at DESC
    """, (user['id'],)).fetchall()
    conn.close()
    return jsonify({'success': True, 'favorites': [dict(f) for f in favorites]})


# ==================== API: 通知列表 ====================
@app.route('/api/notice')
def api_notices():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    conn = get_db()
    notices = conn.execute("""
        SELECT * FROM notices
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 50
    """, (user['id'],)).fetchall()
    conn.close()
    return jsonify({'success': True, 'notices': [dict(n) for n in notices]})


@app.route('/api/notice/read', methods=['POST'])
def api_notice_read():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    notice_id = data.get('notice_id')
    conn = get_db()
    if notice_id:
        conn.execute("UPDATE notices SET is_read = 1 WHERE id = ? AND user_id = ?", (notice_id, user['id']))
    else:
        conn.execute("UPDATE notices SET is_read = 1 WHERE user_id = ?", (user['id'],))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ==================== API: 消息列表 ====================
@app.route('/api/message')
def api_messages():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    conn = get_db()
    messages = conn.execute("""
        SELECT m.*,
               u.nickname as from_nickname,
               u.username as from_username
        FROM messages m
        LEFT JOIN users u ON m.from_user_id = u.id
        WHERE m.to_user_id = ?
        ORDER BY m.created_at DESC
        LIMIT 50
    """, (user['id'],)).fetchall()
    conn.close()
    return jsonify({'success': True, 'messages': [dict(m) for m in messages]})


@app.route('/api/message/send', methods=['POST'])
def api_send_message():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401

    data = request.get_json()
    to_username = data.get('to_username', '').strip()
    content = data.get('content', '').strip()

    if not content:
        return jsonify({'success': False, 'error': '内容不能为空'})

    conn = get_db()
    to_user = conn.execute("SELECT id FROM users WHERE username = ?", (to_username,)).fetchone()
    if not to_user:
        conn.close()
        return jsonify({'success': False, 'error': '用户不存在'})

    conn.execute("""
        INSERT INTO messages (from_user_id, to_user_id, content)
        VALUES (?, ?, ?)
    """, (user['id'], to_user['id'], content))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ============================================================
# 管理员系统 API
# ============================================================

def admin_required(f):
    """管理员权限装饰器"""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or not user.get('is_admin'):
            return jsonify({'error': '无权限'}), 403
        return f(*args, **kwargs)
    return decorated


# --- Famous 管理 ---
@app.route('/api/admin/famous')
@admin_required
def api_admin_famous_list():
    conn = get_db()
    rows = conn.execute("SELECT * FROM famous_users ORDER BY number").fetchall()
    conn.close()
    return jsonify({'success': True, 'items': [dict(r) for r in rows]})


@app.route('/api/admin/famous/<int:fid>', methods=['PUT'])
@admin_required
def api_admin_famous_update(fid):
    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    image_url = data.get('image_url', '').strip()
    like_count = data.get('like_count', 0)
    if not name:
        return jsonify({'error': '名称不能为空'}), 400
    conn = get_db()
    conn.execute("""
        UPDATE famous_users SET name=?, description=?, image_url=?, like_count=?
        WHERE id=?
    """, (name, description, image_url, int(like_count), fid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/admin/famous/<int:fid>', methods=['DELETE'])
@admin_required
def api_admin_famous_delete(fid):
    conn = get_db()
    conn.execute("DELETE FROM famous_users WHERE id=?", (fid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# --- Chef 管理 ---
@app.route('/api/admin/chef')
@admin_required
def api_admin_chef_list():
    conn = get_db()
    rows = conn.execute("SELECT * FROM chef_users ORDER BY number").fetchall()
    conn.close()
    return jsonify({'success': True, 'items': [dict(r) for r in rows]})


@app.route('/api/admin/chef/<int:cid>', methods=['PUT'])
@admin_required
def api_admin_chef_update(cid):
    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    image_url = data.get('image_url', '').strip()
    like_count = data.get('like_count', 0)
    if not name:
        return jsonify({'error': '名称不能为空'}), 400
    conn = get_db()
    conn.execute("""
        UPDATE chef_users SET name=?, description=?, image_url=?, like_count=?
        WHERE id=?
    """, (name, description, image_url, int(like_count), cid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/admin/chef/<int:cid>', methods=['DELETE'])
@admin_required
def api_admin_chef_delete(cid):
    conn = get_db()
    conn.execute("DELETE FROM chef_users WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# --- 用户管理 ---
@app.route('/api/admin/users/<int:uid>', methods=['PUT'])
@admin_required
def api_admin_user_update(uid):
    data = request.get_json()
    nickname = data.get('nickname', '').strip()
    bio = data.get('bio', '').strip()
    level = data.get('level')
    exp = data.get('exp')
    is_admin = 1 if data.get('is_admin') else 0
    if not nickname:
        return jsonify({'error': '昵称不能为空'}), 400
    conn = get_db()
    # Update basic info
    conn.execute("UPDATE users SET nickname=?, bio=?, is_admin=? WHERE id=?", (nickname, bio, is_admin, uid))
    # Update level and exp if provided
    if level is not None and exp is not None:
        level = max(0, min(100, int(level)))
        exp = max(0, int(exp))
        conn.execute("UPDATE users SET level=?, exp=? WHERE id=?", (level, exp, uid))
        # If level is 100, force is_admin
        if level == 100:
            conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# --- 帖子赞数管理 ---
@app.route('/api/admin/topics/<int:tid>/likes', methods=['PUT'])
@admin_required
def api_admin_topic_likes(tid):
    data = request.get_json()
    like_count = max(0, int(data.get('like_count', 0)))
    conn = get_db()
    conn.execute("UPDATE topics SET like_count=? WHERE id=?", (like_count, tid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# --- 标签管理 ---
@app.route('/api/admin/tag/add', methods=['POST'])
@admin_required
def api_admin_tag_add():
    data = request.get_json()
    name = data.get('name', '').strip()
    color = data.get('color', '#888888').strip()
    if not name:
        return jsonify({'success': False, 'error': '标签名称不能为空'})
    conn = get_db()
    conn.execute('INSERT INTO tags (name, color) VALUES (?, ?)', (name, color))
    conn.commit()
    tag_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'success': True, 'tag_id': tag_id})

@app.route('/api/admin/tag/<int:tag_id>', methods=['PUT'])
@admin_required
def api_admin_tag_edit(tag_id):
    data = request.get_json()
    name = data.get('name', '').strip()
    color = data.get('color', '#888888').strip()
    if not name:
        return jsonify({'success': False, 'error': '标签名称不能为空'})
    conn = get_db()
    conn.execute('UPDATE tags SET name=?, color=? WHERE id=?', (name, color, tag_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/tag/<int:tag_id>', methods=['DELETE'])
@admin_required
def api_admin_tag_delete(tag_id):
    conn = get_db()
    conn.execute('DELETE FROM user_tags WHERE tag_id=?', (tag_id,))
    conn.execute('DELETE FROM tags WHERE id=?', (tag_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/admin/user/<int:user_id>/tags', methods=['PUT'])
@admin_required
def api_admin_user_tags(user_id):
    data = request.get_json()
    tag_ids = data.get('tag_ids', [])
    if not isinstance(tag_ids, list):
        tag_ids = []
    conn = get_db()
    conn.execute('DELETE FROM user_tags WHERE user_id=?', (user_id,))
    for tid in tag_ids:
        conn.execute('INSERT INTO user_tags (user_id, tag_id) VALUES (?, ?)', (user_id, tid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ============================================================
# 用户社交系统
# ============================================================

@app.route('/user/<int:uid>')
def user_profile(uid):
    user = get_current_user()
    conn = get_db()
    profile = conn.execute("SELECT id, username, nickname, bio, avatar, is_admin, created_at, level, exp FROM users WHERE id=?", (uid,)).fetchone()
    if not profile:
        conn.close()
        return "用户不存在", 404
    profile = dict(profile)

    # 统计
    following_count = conn.execute("SELECT COUNT(*) FROM follows WHERE follower_id=?", (uid,)).fetchone()[0]
    follower_count = conn.execute("SELECT COUNT(*) FROM follows WHERE following_id=?", (uid,)).fetchone()[0]
    post_count = conn.execute("SELECT COUNT(*) FROM user_posts WHERE user_id=?", (uid,)).fetchone()[0]
    topic_count = conn.execute("SELECT COUNT(*) FROM topics WHERE user_id=?", (uid,)).fetchone()[0]

    # 动态
    posts = conn.execute("""
        SELECT up.*, u.nickname as author_nickname, u.avatar as author_avatar, u.level as author_level, u.is_admin as author_is_admin,
               (SELECT COUNT(*) FROM user_post_likes upl WHERE upl.post_id = up.id) as liked
        FROM user_posts up
        LEFT JOIN users u ON up.user_id = u.id
        WHERE up.user_id = ?
        ORDER BY up.created_at DESC
        LIMIT 30
    """, (uid,)).fetchall()

    # 对方发过的帖子
    topics = conn.execute("""
        SELECT t.id, t.title, t.board_id, t.reply_count, t.like_count, t.created_at,
               b.name as board_name, b.color as board_color, u.level as author_level
        FROM topics t
        LEFT JOIN boards b ON t.board_id = b.id
        LEFT JOIN users u ON t.user_id = u.id
        WHERE t.user_id = ?
        ORDER BY t.created_at DESC
        LIMIT 10
    """, (uid,)).fetchall()

    # 当前用户是否关注了对方
    is_following = False
    if user and user['id'] != uid:
        row = conn.execute("SELECT 1 FROM follows WHERE follower_id=? AND following_id=?", (user['id'], uid)).fetchone()
        is_following = row is not None

    # 获取用户自定义标签
    profile_tags = []
    for row in conn.execute('''
        SELECT t.id, t.name, t.color FROM tags t
        JOIN user_tags ut ON t.id = ut.tag_id
        WHERE ut.user_id = ?
    ''', (uid,)).fetchall():
        profile_tags.append({'id': row[0], 'name': row[1], 'color': row[2]})

    conn.close()
    return render_template('user_profile.html', profile=profile,
                           posts=list(posts), topics=list(topics),
                           following_count=following_count, follower_count=follower_count,
                           post_count=post_count, topic_count=topic_count,
                           is_following=is_following, user=user,
                           profile_tags=profile_tags)


# --- 关注/取关 ---
@app.route('/api/follow/<int:uid>', methods=['POST'])
def api_follow(uid):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    if user['id'] == uid:
        return jsonify({'error': '不能关注自己'}), 400
    conn = get_db()
    existing = conn.execute("SELECT 1 FROM follows WHERE follower_id=? AND following_id=?", (user['id'], uid)).fetchone()
    if existing:
        conn.close()
        return jsonify({'success': True, 'action': 'already'})
    conn.execute("INSERT INTO follows (follower_id, following_id) VALUES (?, ?)", (user['id'], uid))
    conn.commit()
    # 更新被关注者的EXP
    recalc_user_exp(uid)
    conn.close()
    return jsonify({'success': True, 'action': 'followed'})


@app.route('/api/follow/<int:uid>', methods=['DELETE'])
def api_unfollow(uid):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_db()
    conn.execute("DELETE FROM follows WHERE follower_id=? AND following_id=?", (user['id'], uid))
    conn.commit()
    # 更新被取关者的EXP
    recalc_user_exp(uid)
    conn.close()
    return jsonify({'success': True, 'action': 'unfollowed'})


# --- 发动态 ---
@app.route('/api/post', methods=['POST'])
def api_create_post():
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    data = request.get_json()
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'error': '内容不能为空'}), 400
    media_url = data.get('media_url', '').strip()[:500]
    media_type = data.get('media_type', '').strip()[:10]
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_posts (user_id, content, media_url, media_type)
        VALUES (?, ?, ?, ?)
    """, (user['id'], content, media_url, media_type))
    post_id = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'post_id': post_id})


@app.route('/api/post/<int:pid>', methods=['DELETE'])
def api_delete_post(pid):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_db()
    post = conn.execute("SELECT user_id FROM user_posts WHERE id=?", (pid,)).fetchone()
    if not post:
        conn.close()
        return jsonify({'error': '动态不存在'}), 404
    if post['user_id'] != user['id'] and not user.get('is_admin'):
        conn.close()
        return jsonify({'error': '无权删除'}), 403
    conn.execute("DELETE FROM user_posts WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/post/<int:pid>/like', methods=['POST'])
def api_like_post(pid):
    user = get_current_user()
    if not user:
        return jsonify({'error': '请先登录'}), 401
    conn = get_db()
    existing = conn.execute("SELECT 1 FROM user_post_likes WHERE user_id=? AND post_id=?", (user['id'], pid)).fetchone()
    if existing:
        conn.execute("DELETE FROM user_post_likes WHERE user_id=? AND post_id=?", (user['id'], pid))
        conn.execute("UPDATE user_posts SET like_count = MAX(0, like_count - 1) WHERE id=?", (pid,))
        action = 'unliked'
    else:
        conn.execute("INSERT INTO user_post_likes (user_id, post_id) VALUES (?, ?)", (user['id'], pid))
        conn.execute("UPDATE user_posts SET like_count = like_count + 1 WHERE id=?", (pid,))
        action = 'liked'
    conn.commit()
    new_count = conn.execute("SELECT like_count FROM user_posts WHERE id=?", (pid,)).fetchone()[0]
    conn.close()
    return jsonify({'success': True, 'action': action, 'like_count': new_count})


# --- 关注的人的发帖 ---
@app.route('/following')
def following_page():
    user = get_current_user()
    if not user:
        flash('请先登录', 'error')
        return redirect(url_for('login'))
    conn = get_db()
    posts = conn.execute("""
        SELECT up.*, u.nickname as author_nickname, u.avatar as author_avatar, u.id as author_id, u.level as author_level,
               (SELECT COUNT(*) FROM user_post_likes upl WHERE upl.post_id = up.id) as liked,
               (SELECT COUNT(*) FROM user_post_likes upl WHERE upl.post_id = up.id AND upl.user_id = ?) as i_liked
        FROM user_posts up
        LEFT JOIN users u ON up.user_id = u.id
        WHERE up.user_id IN (SELECT following_id FROM follows WHERE follower_id = ?)
        ORDER BY up.created_at DESC
        LIMIT 50
    """, (user['id'], user['id'])).fetchall()
    conn.close()
    return render_template('following.html', posts=list(posts), user=user)



if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5006
    init_db()
    app.run(host="0.0.0.0", port=port, debug=False)
