# -*- coding: utf-8 -*-

from flask import render_template, request, Blueprint, g, session, redirect, url_for
import logging, json
import mongo, os
from user import require_login
from models import ConnectionString

mod = Blueprint('connection_string', __name__, url_prefix='/connection')

@mod.route('/list', methods=['GET'])
def list():
    return render_template('connection_string/list.html', connections=ConnectionString.all())

@mod.route('/new', methods=['GET'])
@require_login
def new():
    url = 'mysql://scott:tiger@localhost/foo'
    return render_template('connection_string/new.html', url = url, users=[g.user.username])

@mod.route('/', methods=['GET', 'POST'])
@mod.route('/<name>', methods=['GET', 'POST'])
@require_login
def edit(name=None):
    users = []
    if request.method == 'GET':
        logging.info('loading connection string %s', name)
        if not name:
            return redirect(url_for('.new'))

        connection = ConnectionString.find(name)

        url = connection.url
        name = connection.name
        headers = connection.headers
        users.append(connection.owner)
    else:
        url = request.form['url']
        name = request.form.get('name')
        headers = request.form.get('headers')
        users.append(session.user)

        if name == 'new':
            name = None

        if name:
            ConnectionString.create_or_update(name=name, url=url, headers=headers)
            return redirect(url_for('.edit', name = name))

    return render_template('connection_string/new.html',
                           name = name,
                           headers = headers,
                           users = users,
                           url = url)
