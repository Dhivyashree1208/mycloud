from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory
from flask_login import login_required, current_user
from bson import ObjectId
from datetime import datetime
from . import mongo
from .utils import allowed_file, save_file
import os

main = Blueprint('main', __name__)

@main.route('/')
@login_required
def index():
    search = request.args.get('search', '').strip()
    favorites_only = request.args.get('favorites') == 'true'

    query = {
        'user_id': current_user.id,
        'trashed': False  # Exclude trashed files
    }
    if search:
        query['filename'] = {'$regex': search, '$options': 'i'}
    if favorites_only:
        query['favorite'] = True

    files = list(mongo.db.files.find(query).sort('upload_time', -1))
    for f in files:
        f['_id'] = str(f['_id'])
        if isinstance(f.get('shared_to'), str):
            f['shared_to'] = [f['shared_to']]

    return render_template('dashboard.html', files=files)

@main.route('/upload', methods=['POST'])
@login_required
def upload():
    file = request.files['file']
    folder = request.form.get('folder', 'root')
    description = request.form.get('description', '')

    if file and allowed_file(file.filename):
        filename, path = save_file(file, folder)
        file.seek(0)
        mongo.db.files.insert_one({
            'filename': filename,
            'folder': folder,
            'description': description,
            'user_id': current_user.id,
            'upload_time': datetime.now(),
            'size': len(file.read()),
            'type': file.content_type,
            'favorite': False,
            'shared_to': [],
            'trashed': False   # Add this line
        })
        flash('File uploaded successfully!')
    else:
        flash('Invalid file type.')
    return redirect(url_for('main.index'))

@main.route('/delete/<file_id>')
@login_required
def delete(file_id):
    mongo.db.files.update_one(
        {'_id': ObjectId(file_id), 'user_id': current_user.id},
        {'$set': {'trashed': True}}
    )
    flash('File moved to Trash.')
    return redirect(url_for('main.index'))

@main.route('/restore/<file_id>')
@login_required
def restore(file_id):
    mongo.db.files.update_one(
        {'_id': ObjectId(file_id), 'user_id': current_user.id},
        {'$set': {'trashed': False}}
    )
    flash('File restored from Trash.')
    return redirect(url_for('main.trash'))

@main.route('/permanent_delete/<file_id>')
@login_required
def permanent_delete(file_id):
    file = mongo.db.files.find_one({'_id': ObjectId(file_id), 'user_id': current_user.id})
    if file:
        file_path = os.path.join('static', 'uploads', file.get('folder', ''), file['filename'])
        if os.path.exists(file_path):
            os.remove(file_path)
        mongo.db.files.delete_one({'_id': ObjectId(file_id)})
        flash('File permanently deleted.')
    else:
        flash('File not found or permission denied.')
    return redirect(url_for('main.trash'))

@main.route('/share/<file_id>', methods=['POST'])
@login_required
def share(file_id):
    recipient_email = request.form.get('email')
    file = mongo.db.files.find_one({'_id': ObjectId(file_id), 'user_id': current_user.id})
    if file:
        mongo.db.shared.insert_one({
            'file_id': file_id,
            'shared_by': current_user.id,
            'shared_to': recipient_email,
            'shared_at': datetime.now()
        })

        current_shared = file.get('shared_to', [])
        if isinstance(current_shared, str):
            current_shared = [current_shared]
        if recipient_email not in current_shared:
            current_shared.append(recipient_email)
        mongo.db.files.update_one({'_id': ObjectId(file_id)}, {'$set': {'shared_to': current_shared}})
        flash(f"File shared with {recipient_email}")
    else:
        flash("File not found or permission denied.")
    return redirect(url_for('main.index'))

@main.route('/shared')
@login_required
def shared():
    shared_records = list(mongo.db.shared.find({'shared_by': current_user.id}))
    shared_dict = {}
    for record in shared_records:
        file_id = record['file_id']
        shared_dict.setdefault(file_id, []).append(record['shared_to'])

    file_ids = list(shared_dict.keys())
    shared_files = list(mongo.db.files.find({'_id': {'$in': [ObjectId(fid) for fid in file_ids]}}))

    for file in shared_files:
        file['_id'] = str(file['_id'])
        file['shared_to'] = shared_dict.get(file['_id'], [])

    return render_template('dashboard.html', files=shared_files)

@main.route('/favorite/<file_id>')
@login_required
def favorite(file_id):
    file = mongo.db.files.find_one({'_id': ObjectId(file_id), 'user_id': current_user.id})
    if file:
        current_status = file.get('favorite', False)
        mongo.db.files.update_one({'_id': ObjectId(file_id)}, {'$set': {'favorite': not current_status}})
        flash("Favorite status updated.")
    else:
        flash("File not found or permission denied.")
    return redirect(url_for('main.index'))

@main.route('/download/<file_id>')
@login_required
def download(file_id):
    file = mongo.db.files.find_one({'_id': ObjectId(file_id), 'user_id': current_user.id})
    if file:
        folder = file.get('folder', 'root')
        upload_path = os.path.join('static', 'uploads', folder)
        return send_from_directory(upload_path, file['filename'], as_attachment=True)
    else:
        flash("File not found or permission denied.")
        return redirect(url_for('main.index'))

@main.route('/trash')
@login_required
def trash():
    trashed_files = list(mongo.db.files.find({
        'user_id': current_user.id,
        'trashed': True
    }).sort('upload_time', -1))

    for f in trashed_files:
        f['_id'] = str(f['_id'])
        if isinstance(f.get('shared_to'), str):
            f['shared_to'] = [f['shared_to']]

    return render_template('dashboard.html', files=trashed_files)
