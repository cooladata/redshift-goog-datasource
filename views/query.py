# -*- coding: utf-8 -*-

from flask import render_template, request, Blueprint, Response, redirect, url_for
import logging, json
from models import Query
from datetime import datetime, timedelta
from models import Transformer
from models import ConnectionString
from user import require_login

mod = Blueprint('query', __name__, url_prefix='/query')

def query_db(connection, query, args):
    if not connection:
        raise ValueError('Missing Connection String')

    from sqlalchemy import create_engine

    db = create_engine(connection.url)

    sql = query.format(**args)
    cur = db.execute(sql)
    rows = cur.fetchall()

    if len(rows) > 0:
        columns_order = [column for column, value in rows[0].items()]
    else:
        columns_order = []

    data = [dict((column, value) for column, value in row.items()) for row in rows]

    type_convert = {"unicode": "string", "string": "string", "long": "number", "int": "number", "datetime": "datetime", "float": "number"}
    if len(data) > 0:
        description = dict([(name, (type_convert[type(value).__name__], name)) for name, value in data[0].iteritems()])
    else:
        description = {}

    return description, data, columns_order

def save(name, sql, meta_vars, connection):
    Query.create_or_update(name = name,
                           sql = sql,
                           meta_vars = meta_vars,
                           connection = ConnectionString.find(connection))

def convert_value(val, type):
    if not val:
        return None

    if type == 'string':
        return val
    elif type == 'integer':
        return int(val)
    elif type == 'float':
        return float(val)

def vars_with_default_value(meta_vars, vars):
    result = {}
    for key, options in meta_vars.iteritems():
        val = vars.get(key)

        if not val:
            val = options.get('default')

        result[key] = convert_value(val, options['type'])

    return result

def data_to_datatable(description, data, columns_order):
    import gviz_api

    data_table = gviz_api.DataTable(description)
    data_table.LoadData(data)

    return data_table, columns_order

def query_execute_sql(connection, sql, meta_vars, vars):
    meta_vars = dict(meta_vars)
    vars = dict(vars)

    vars = vars_with_default_value(meta_vars, vars)

    logging.info('execute query %s %s %s', sql, vars, meta_vars)

    description, data, columns_order = query_db(connection, sql, vars)

    return description, data, columns_order

@mod.route('/list', methods=['GET'])
@require_login
def list():
    queries = Query.objects()

    return render_template('query/list.html', queries=queries)

def handle_datetime(obj):
    return obj.isoformat() if isinstance(obj, datetime) else None

@mod.route('/new', methods=['GET'])
@require_login
def new():
    sql = "select * from socialism_online.cdrs_raw \n" + \
          "where\n\textract(year from dt_timestamp)={Year} and \n" + \
          "\textract(month from dt_timestamp)={Month} and \n" + \
          "\textract(day from dt_timestamp)={Day}"

    yesterday = datetime.today() - timedelta(days=1)
    meta_vars=[
        ("Year", {"type": "integer", "default": yesterday.year}),
        ("Month", {"type": "integer", "default": yesterday.month}),
        ("Day", {"type": "integer", "default": yesterday.day})]

    vars = [('Year', None), ('Month', None), ('Day', None)]

    return render_template('query/create_or_edit.html',
        sql = sql,
        vars = vars,
        meta_vars = meta_vars)

@mod.route('/', methods=['POST', 'GET'])
@mod.route('/<name>', methods=['POST', 'GET'])
@require_login
def edit(name=None):
    if request.method == 'POST':
        def extract_meta_var_fields():
            index = 0

            meta = []
            while True:
                name = request.form.get('var-name%d' % index)
                if not name:
                    return meta

                type = request.form.get('var-type%d' % index, 'string')
                default = request.form.get('var-default%d' % index, 'string')

                meta.append((name, {'default': default, 'type': type}))

                index += 1

        def vars_from_request(meta_vars, empty_vars):
            vars = []
            for name, options in meta_vars:
                value = request.form.get(name)

                if value:
                    value = convert_value(value, options.get('type'))
                elif not empty_vars:
                    continue

                vars.append((name, value))

            return vars

        meta_vars = extract_meta_var_fields()

        sql = request.form['sql']

        name = request.form.get('query-name')

        if name == 'new':
            name = None

        connection = ConnectionString.find(request.form.get('connection_string'))

        if name:
            save(name, sql, meta_vars, connection)
            full_vars = vars_from_request(meta_vars, False)
            return redirect(url_for('.edit', name = name, **dict(full_vars)))

        vars = vars_from_request(meta_vars, True)
    else:
        if not name:
            return redirect(url_for('.new'))

        vars = []
        for key, value in request.args.iteritems():
            if not value:
                continue

            vars.append((key, value))

        query = Query.find(name)

        if not query:
            return redirect(url_for('.new'))

        sql = query.sql
        meta_vars = query.meta_vars
        connection = query.connection

    transform = request.args.get('transform', None)

    raw_data = not request.args.get('json', None) is None

    try:
        json_data = None

        if connection:
            description, data, columns_order = query_execute_sql(connection, sql, meta_vars, vars)

            if transform:
                data = Transformer.execute(transform, data)

            if raw_data:
                json_data = json.dumps(data, default=handle_datetime)
            elif len(data) > 0:
                data_table, columns_order = data_to_datatable(description, data, columns_order)
                json_data = data_table.ToJSon(columns_order=columns_order)

        if not json_data:
            json_data = json.dumps([])
            data_table = None

        error = ''
    except Exception, ex:
        logging.error("Failed to execute query %s", ex)
        error = str(ex)
        data_table = None

    if not request.args.get('gwiz', None) is None:
        return Response(data_table.ToJSonResponse(columns_order=columns_order),  mimetype='application/json')
    if not request.args.get('json', None) is None:
        if error:
            return Response(error)

        return Response(json_data,  mimetype='application/json')
    elif not request.args.get('html', None) is None:
        return Response(data_table.ToHtml(columns_order=columns_order))
    elif not request.args.get('csv', None) is None:
        return Response(data_table.ToCsv(columns_order=columns_order), mimetype='text/csv')
    else:
        json_data = data_table.ToJSon(columns_order=columns_order) if data_table else None

        full_vars = []
        vars = dict(vars)
        for key, options in meta_vars:
            val = vars.get(key)
            if val:
                full_vars.append((key, val))
            else:
                full_vars.append((key, None))

    return render_template('query/create_or_edit.html',
        name = name,
        sql = sql,
        error = error,
        json = json_data,
        connection = connection,
        connections = ConnectionString.all(),
        meta_vars = meta_vars,
        vars = full_vars)