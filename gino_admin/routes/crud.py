from typing import List, Text, Tuple, Union
import asyncpg
from sanic.request import Request
import datetime
from gino_admin import auth, utils
from gino_admin.core import admin, cfg
from gino_admin.routes.logic import render_add_or_edit_form, render_model_view, get_by_params


@admin.route("/<model_id>", methods=["GET"])
@auth.token_validation()
async def model_view_table(
    request: Request, model_id: Text, flash_messages: Union[List[Tuple], Tuple] = None
):
    if flash_messages and not isinstance(flash_messages[0], tuple):
        request["flash"](*flash_messages)
    elif flash_messages:
        for flash in flash_messages:
            request["flash"](*flash)
    return await render_model_view(request, model_id)


@admin.route("/<model_id>/edit", methods=["GET"])
@auth.token_validation()
async def model_edit_view(request, model_id):
    _id = utils.extract_obj_id_from_query(dict(request.query_args)["_id"])
    return await render_add_or_edit_form(request, model_id, _id)


@admin.route("/<model_id>/edit", methods=["POST"])
@auth.token_validation()
async def model_edit_post(request, model_id):
    previous_id = utils.extract_obj_id_from_query(dict(request.query_args)["_id"])
    model_data = cfg.models[model_id]
    model = model_data["model"]
    request_params = {
        key: request.form[key][0] if request.form[key][0] != "None" else None
        for key in request.form
    }
    previous_id = utils.correct_types(previous_id, model_data["columns_data"])
    print(previous_id)
    obj = await get_by_params(previous_id, model)
    old_obj = obj.to_dict()
    if model_data["hashed_indexes"]:
        request_params = utils.reverse_hash_names(model_id, request_params)
    request_params = utils.correct_types(request_params, model_data["columns_data"])
    try:
        await obj.update(**request_params).apply()
        changes = utils.get_changes(old_obj, obj.to_dict())
        new_obj_id = utils.get_obj_id_from_row(model_data, request_params)
        print(new_obj_id)
        message = f'Object with id {previous_id} was updated. Changes: from {changes["from"]} to {changes["to"]}'
        request["flash"](message, "success")
        request["history_action"]["log_message"] = message
        request["history_action"]["object_id"] = previous_id
    except asyncpg.exceptions.ForeignKeyViolationError:
        request["flash"](
            f"ForeignKey error. "
            f"Impossible to edit {model_data['key']} field for row {previous_id}, "
            f"because exists objects that depend on it. ",
            "error",
        )
    except asyncpg.exceptions.UniqueViolationError:
        request["flash"](
            f"{model_id.capitalize()} with such id already exists", "error"
        )
    except asyncpg.exceptions.NotNullViolationError as e:
        column = e.args[0].split("column")[1].split("violates")[0]
        request["flash"](f"Field {column} cannot be null", "error")
    return await render_add_or_edit_form(
        request, model_id, new_obj_id
    )


@admin.route("/<model_id>/add", methods=["GET"])
@auth.token_validation()
async def model_add_view(request, model_id):
    return await render_add_or_edit_form(request, model_id)


@admin.route("/<model_id>/add", methods=["POST"])
@auth.token_validation()
async def model_add(request, model_id):
    model_data = cfg.models[model_id]
    request_params = {key: request.form[key][0] for key in request.form}
    not_filled = [x for x in model_data["required_columns"] if x not in request_params]
    if not_filled:
        request["flash"](f"Fields {not_filled} required. Please fill it", "error")
    else:
        if model_data["hashed_indexes"]:
            request_params = utils.reverse_hash_names(model_id, request_params)
        try:
            request_params = utils.correct_types(
                request_params, model_data["columns_data"]
            )
            obj = await model_data["model"].create(**request_params)
            obj_id = utils.get_obj_id_from_row(model_data, request_params)
            message = f'Object with {obj_id} was added.'
            request["flash"](message, "success")
            request["history_action"]["log_message"] = message
            request["history_action"]["object_id"] = obj_id
        except (
            asyncpg.exceptions.StringDataRightTruncationError,
            ValueError,
            asyncpg.exceptions.ForeignKeyViolationError,
        ) as e:
            request["flash"](e.args, "error")
        except asyncpg.exceptions.UniqueViolationError:
            request["flash"](
                f"{model_id.capitalize()} with such id already exists", "error"
            )
        except asyncpg.exceptions.NotNullViolationError as e:
            column = e.args[0].split("column")[1].split("violates")[0]
            request["flash"](f"Field {column} cannot be null", "error")

    return await render_add_or_edit_form(request, model_id)


@admin.route("/<model_id>/delete", methods=["POST"])
@auth.token_validation()
async def model_delete(request, model_id):
    """ route for delete item per row """
    model_data = cfg.models[model_id]
    request_params = {key: request.form[key][0] for key in request.form}
    obj_id = utils.get_obj_id_from_row(model_data, request_params)
    
    try:
        obj = get_by_params(obj_id, model_data["model"])
        await obj.delete()
        message = f"Object with {obj_id} was deleted"
        flash_message = (message, "success")
        request["history_action"]["log_message"] = message
        request["history_action"]["object_id"] = obj_id
    except asyncpg.exceptions.ForeignKeyViolationError as e:
        flash_message = (str(e.args), "error")

    return await model_view_table(request, model_id, flash_message)


@admin.route("/<model_id>/delete_all", methods=["POST"])
@auth.token_validation()
async def model_delete_all(request, model_id):
    try:
        await cfg.models[model_id]["model"].delete.where(True).gino.status()
        message = f"All objects in {model_id} was deleted"
        flash_message = (message, "success")
        request["history_action"]["log_message"] = message
        request["history_action"]["object_id"] = model_id
    except asyncpg.exceptions.ForeignKeyViolationError as e:
        flash_message = (e.args, "error")
    return await model_view_table(request, model_id, flash_message)
