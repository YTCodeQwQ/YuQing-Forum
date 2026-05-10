# -*- coding: utf-8 -*-
"""独立管理员系统"""
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from functools import wraps

admin_bp = Blueprint('admin', __name__, url_prefix='/manage')

def get_db():
    return sqlite3.connect('/root/workspace/forum.db')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        user_id = session['user_id']
        conn = get_db()
        cur = conn.execute('SELECT is_admin FROM users WHERE id = ?', (user_id,))
        user = cur.fetchone()
        conn.close()
        if not user or not user[0]:
            return '<h1>权限不足，需要管理员账号</h1><a href="/">返回首页</a>'
        return f(*args, **kwargs)
    return decorated_function

def get_user_tags(user_id):
    """获取用户的所有标签"""
    conn = get_db()
    tags = conn.execute('''
        SELECT t.id, t.name, t.color FROM tags t
        JOIN user_tags ut ON t.id = ut.tag_id
        WHERE ut.user_id = ?
    ''', (user_id,)).fetchall()
    conn.close()
    return tags

def set_user_tags(user_id, tag_ids):
    """设置用户的标签"""
    conn = get_db()
    conn.execute('DELETE FROM user_tags WHERE user_id = ?', (user_id,))
    for tag_id in tag_ids:
        if tag_id:
            conn.execute('INSERT INTO user_tags (user_id, tag_id) VALUES (?, ?)', (user_id, tag_id))
    conn.commit()
    conn.close()

# ============ 管理员首页 ============
@admin_bp.route('/')
@login_required
def index():
    conn = get_db()
    
    # 统计
    user_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    topic_count = conn.execute('SELECT COUNT(*) FROM topics').fetchone()[0]
    reply_count = conn.execute('SELECT COUNT(*) FROM replies').fetchone()[0]
    famous_count = conn.execute('SELECT COUNT(*) FROM famous_users').fetchone()[0]
    chef_count = conn.execute('SELECT COUNT(*) FROM chef_users').fetchone()[0]
    
    # 最新用户
    recent_users = conn.execute('''
        SELECT id, username, nickname, level, is_admin, created_at 
        FROM users ORDER BY id DESC LIMIT 5
    ''').fetchall()
    
    # 最新帖子
    recent_topics = conn.execute('''
        SELECT t.id, t.title, t.created_at, u.nickname, b.name
        FROM topics t
        LEFT JOIN users u ON t.user_id = u.id
        LEFT JOIN boards b ON t.board_id = b.id
        ORDER BY t.id DESC LIMIT 5
    ''').fetchall()
    
    conn.close()
    
    return render_template('admin/index.html',
        user_count=user_count,
        topic_count=topic_count,
        reply_count=reply_count,
        famous_count=famous_count,
        chef_count=chef_count,
        recent_users=recent_users,
        recent_topics=recent_topics
    )

# ============ 标签管理 ============
@admin_bp.route('/tags')
@login_required
def tags():
    conn = get_db()
    tags = conn.execute('SELECT id, name, color, created_at FROM tags ORDER BY id').fetchall()
    
    # 统计每个标签的用户数
    tag_counts = {}
    for t in tags:
        count = conn.execute('SELECT COUNT(*) FROM user_tags WHERE tag_id = ?', (t[0],)).fetchone()[0]
        tag_counts[t[0]] = count
    
    conn.close()
    return render_template('admin/tags.html', tags=tags, tag_counts=tag_counts)

@admin_bp.route('/tag/add', methods=['POST'])
@login_required
def tag_add():
    name = request.form.get('name')
    color = request.form.get('color', '#888888')
    
    conn = get_db()
    try:
        cur = conn.execute('INSERT INTO tags (name, color) VALUES (?, ?)', (name, color))
        conn.commit()
        tag_id = cur.lastrowid
        conn.close()
        return jsonify({'success': True, 'id': tag_id})
    except:
        conn.close()
        return jsonify({'success': False, 'error': '标签名已存在'})

@admin_bp.route('/tag/<int:tag_id>/edit', methods=['POST'])
@login_required
def tag_edit(tag_id):
    name = request.form.get('name')
    color = request.form.get('color', '#888888')
    
    conn = get_db()
    conn.execute('UPDATE tags SET name=?, color=? WHERE id=?', (name, color, tag_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@admin_bp.route('/tag/<int:tag_id>/delete', methods=['POST'])
@login_required
def tag_delete(tag_id):
    conn = get_db()
    conn.execute('DELETE FROM user_tags WHERE tag_id=?', (tag_id,))
    conn.execute('DELETE FROM tags WHERE id=?', (tag_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============ 用户管理 ============
@admin_bp.route('/users')
@login_required
def users():
    conn = get_db()
    users = conn.execute('''
        SELECT u.id, u.username, u.nickname, u.level, u.exp, u.is_admin, 
               COALESCE(u.is_banned, 0) as is_banned, u.created_at
        FROM users u ORDER BY u.id DESC
    ''').fetchall()
    
    # 获取所有标签
    all_tags = conn.execute('SELECT id, name, color FROM tags').fetchall()
    
    # 获取每个用户的标签
    user_tags_map = {}
    for u in users:
        tags = conn.execute('''
            SELECT t.id, t.name, t.color FROM tags t
            JOIN user_tags ut ON t.id = ut.tag_id
            WHERE ut.user_id = ?
        ''', (u[0],)).fetchall()
        user_tags_map[u[0]] = tags
    
    conn.close()
    return render_template('admin/users.html', users=users, all_tags=all_tags, user_tags_map=user_tags_map)

@admin_bp.route('/user/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def user_edit(user_id):
    conn = get_db()
    
    if request.method == 'POST':
        nickname = request.form.get('nickname')
        level = request.form.get('level', 0)
        exp = request.form.get('exp', 0)
        is_admin = 1 if request.form.get('is_admin') else 0
        is_banned = 1 if request.form.get('is_banned') else 0
        tag_ids = request.form.getlist('tags')
        
        conn.execute('''
            UPDATE users SET nickname=?, level=?, exp=?, is_admin=?, is_banned=?
            WHERE id=?
        ''', (nickname, level, exp, is_admin, is_banned, user_id))
        
        # 更新标签
        set_user_tags(user_id, [int(t) for t in tag_ids if t])
        
        conn.commit()
        conn.close()
        return redirect(url_for('admin.users'))
    
    user = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    all_tags = conn.execute('SELECT id, name, color FROM tags').fetchall()
    user_tags = get_user_tags(user_id)
    conn.close()
    return render_template('admin/user_edit.html', user=user, all_tags=all_tags, user_tags=[t[0] for t in user_tags])

@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
@login_required
def user_delete(user_id):
    if session.get('user_id') == user_id:
        return jsonify({'error': '不能删除自己'}), 400
    
    conn = get_db()
    conn.execute('DELETE FROM user_tags WHERE user_id=?', (user_id,))
    conn.execute('DELETE FROM users WHERE id=?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@admin_bp.route('/user/<int:user_id>/ban', methods=['POST'])
@login_required
def user_ban(user_id):
    conn = get_db()
    conn.execute('UPDATE users SET is_banned=1 WHERE id=?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@admin_bp.route('/user/<int:user_id>/unban', methods=['POST'])
@login_required
def user_unban(user_id):
    conn = get_db()
    conn.execute('UPDATE users SET is_banned=0 WHERE id=?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============ 帖子管理 ============
@admin_bp.route('/topics')
@login_required
def topics():
    board_id = request.args.get('board')
    search = request.args.get('search')
    
    conn = get_db()
    query = '''
        SELECT t.id, t.title, t.content, t.view_count, t.like_count, t.reply_count,
               t.is_pinned, t.created_at, u.nickname, b.name as board_name
        FROM topics t
        LEFT JOIN users u ON t.user_id = u.id
        LEFT JOIN boards b ON t.board_id = b.id
        WHERE 1=1
    '''
    params = []
    
    if board_id:
        query += ' AND t.board_id=?'
        params.append(board_id)
    if search:
        query += ' AND (t.title LIKE ? OR t.content LIKE ?)'
        params.extend([f'%{search}%', f'%{search}%'])
    
    query += ' ORDER BY t.id DESC LIMIT 100'
    topics = conn.execute(query, params).fetchall()
    
    boards = conn.execute('SELECT id, name FROM boards').fetchall()
    conn.close()
    
    return render_template('admin/topics.html', topics=topics, boards=boards, current_board=board_id, search=search)

@admin_bp.route('/topic/<int:topic_id>/pin', methods=['POST'])
@login_required
def topic_pin(topic_id):
    conn = get_db()
    topic = conn.execute('SELECT is_pinned FROM topics WHERE id=?', (topic_id,)).fetchone()
    if topic:
        new_pin = 0 if topic[0] else 1
        conn.execute('UPDATE topics SET is_pinned=? WHERE id=?', (new_pin, topic_id))
        conn.commit()
    conn.close()
    return jsonify({'success': True, 'is_pinned': new_pin if topic else 0})

@admin_bp.route('/topic/<int:topic_id>/delete', methods=['POST'])
@login_required
def topic_delete(topic_id):
    conn = get_db()
    conn.execute('DELETE FROM topics WHERE id=?', (topic_id,))
    conn.execute('DELETE FROM replies WHERE topic_id=?', (topic_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============ 回复管理 ============
@admin_bp.route('/replies')
@login_required
def replies():
    topic_id = request.args.get('topic')
    
    conn = get_db()
    if topic_id:
        replies = conn.execute('''
            SELECT r.id, r.content, r.like_count, r.created_at,
                   u.nickname, t.title
            FROM replies r
            LEFT JOIN users u ON r.user_id = u.id
            LEFT JOIN topics t ON r.topic_id = t.id
            WHERE r.topic_id=?
            ORDER BY r.id DESC
        ''', (topic_id,)).fetchall()
    else:
        replies = conn.execute('''
            SELECT r.id, r.content, r.like_count, r.created_at,
                   u.nickname, t.title
            FROM replies r
            LEFT JOIN users u ON r.user_id = u.id
            LEFT JOIN topics t ON r.topic_id = t.id
            ORDER BY r.id DESC LIMIT 100
        ''').fetchall()
    
    conn.close()
    return render_template('admin/replies.html', replies=replies, topic_id=topic_id)

@admin_bp.route('/reply/<int:reply_id>/delete', methods=['POST'])
@login_required
def reply_delete(reply_id):
    conn = get_db()
    conn.execute('DELETE FROM replies WHERE id=?', (reply_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============ 榜单管理 ============
@admin_bp.route('/famous')
@login_required
def famous():
    conn = get_db()
    famous_users = conn.execute('''
        SELECT f.id, f.user_id, f.reason, f.created_at, u.nickname, u.level
        FROM famous_users f
        LEFT JOIN users u ON f.user_id = u.id
        ORDER BY f.id DESC
    ''').fetchall()
    conn.close()
    return render_template('admin/famous.html', famous_users=famous_users)

@admin_bp.route('/famous/add', methods=['POST'])
@login_required
def famous_add():
    user_id = request.form.get('user_id')
    reason = request.form.get('reason')
    
    conn = get_db()
    conn.execute('INSERT INTO famous_users (user_id, reason) VALUES (?, ?)', (user_id, reason))
    conn.commit()
    conn.close()
    return redirect(url_for('admin.famous'))

@admin_bp.route('/famous/<int:famous_id>/delete', methods=['POST'])
@login_required
def famous_delete(famous_id):
    conn = get_db()
    conn.execute('DELETE FROM famous_users WHERE id=?', (famous_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@admin_bp.route('/chef')
@login_required
def chef():
    conn = get_db()
    chef_users = conn.execute('''
        SELECT c.id, c.user_id, c.reason, c.created_at, u.nickname, u.level
        FROM chef_users c
        LEFT JOIN users u ON c.user_id = u.id
        ORDER BY c.id DESC
    ''').fetchall()
    conn.close()
    return render_template('admin/chef.html', chef_users=chef_users)

@admin_bp.route('/chef/add', methods=['POST'])
@login_required
def chef_add():
    user_id = request.form.get('user_id')
    reason = request.form.get('reason')
    
    conn = get_db()
    conn.execute('INSERT INTO chef_users (user_id, reason) VALUES (?, ?)', (user_id, reason))
    conn.commit()
    conn.close()
    return redirect(url_for('admin.chef'))

@admin_bp.route('/chef/<int:chef_id>/delete', methods=['POST'])
@login_required
def chef_delete(chef_id):
    conn = get_db()
    conn.execute('DELETE FROM chef_users WHERE id=?', (chef_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ============ 版块管理 ============
@admin_bp.route('/boards')
@login_required
def boards():
    conn = get_db()
    boards = conn.execute('SELECT * FROM boards ORDER BY sort_order').fetchall()
    conn.close()
    return render_template('admin/boards.html', boards=boards)

@admin_bp.route('/board/<int:board_id>/edit', methods=['GET', 'POST'])
@login_required
def board_edit(board_id):
    conn = get_db()
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        icon = request.form.get('icon')
        color = request.form.get('color')
        sort_order = request.form.get('sort_order', 0)
        
        conn.execute('''
            UPDATE boards SET name=?, description=?, icon=?, color=?, sort_order=?
            WHERE id=?
        ''', (name, description, icon, color, sort_order, board_id))
        conn.commit()
        conn.close()
        return redirect(url_for('admin.boards'))
    
    board = conn.execute('SELECT * FROM boards WHERE id=?', (board_id,)).fetchone()
    conn.close()
    return render_template('admin/board_edit.html', board=board)
