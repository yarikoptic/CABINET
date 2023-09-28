from datetime import datetime
import os
import sys

from src.logger import LOGGER
from src.utilities import extract_from_json

def validate_parameter_json(json_path):
    """
    Validates the parameter JSON to ensure CABINET can run.
    :param j_args: dict, the parsed parameter JSON
    :param json_path: str, filepath of the parameter JSON
    :return: j_args, the parameter j_args dict with empty keys set to defaults
    """

    LOGGER.info(f"Getting Arguments from arg file: {json_path}")
    
    j_args = extract_from_json(json_path)

    LOGGER.info("Validating parameter JSON\n")

    is_valid = True

    # validate cabinet key
    if "cabinet" not in j_args.keys():
        LOGGER.error("Missing key in parameter JSON: 'cabinet'")
        is_valid = False
    else:
        j_args, is_valid = validate_cabinet_options(j_args)

    # if cabinet key is valid, validate stages key
    if is_valid:
        if "stages" not in j_args.keys():
            LOGGER.error("Missing key in parameter JSON: 'stages'")
            is_valid = False
        else:
            for requested_stage in j_args["cabinet"]["stages"]:
                if requested_stage not in j_args["stages"].keys():
                    LOGGER.error(f"Parameters for {requested_stage} not found. Please add parameters for {requested_stage} to 'stages'.")
                    is_valid = False
                else:
                    j_args, is_valid = validate_stage(j_args, requested_stage)

    # if stages key is valid, validate binds/mounts
    if is_valid:
        bind_type = "binds"
        if j_args['cabinet']['container_type'] == "docker":
            bind_type = "mounts"
        for stage in j_args['cabinet']['stages']:
            is_valid = is_valid and validate_binds(stage, j_args, bind_type)

    if not is_valid:
        LOGGER.error(f"Parameter JSON {json_path} is invalid. See examples directory for examples.")
        sys.exit()
    elif j_args['cabinet']['verbose']:
        LOGGER.info(f"Parameter JSON {json_path} is valid.\nValidated JSON: {j_args}")

    return j_args

def validate_cabinet_options(j_args):
    """
    Validates the cabinet options from the param json.
    :param j_args: dict, the parsed json.
    :returns j_args: dict, the parsed json with any missing arguments set to default values
    :returns is_valid: bool, if the json is valid
    """
    is_valid = True
    options = {
        "container_type": {
            "required": True,
            "values": ["singularity", "docker"],
            "type": str
        },
        "stages": {
            "required": True,
            "type": list
        },
        "verbose": {
            "required": False,
            "default": False,
            "type": bool
        },
        "log_directory": {
            "required": False,
            "default": "",
            "type": str
        },
        "job_id": {
            "required": False,
            "default": datetime.now().timestamp(),
            "type": str
        },
        "handle_missing_host_paths": {
            "required": False,
            "default": "stop",
            "values": ["stop", "allow", "make_directories"],
            "type": str
        },
        "stop_on_stage_fail": {
            "required": False,
            "default": True,
            "type": bool
        }
    }

    for option, requirements in options.items():
        # enforce required keys
        if option not in j_args['cabinet'].keys():
            if requirements['required']:
                is_valid = False
                LOGGER.error(f"Missing required key in cabinet options: {option}")
                continue
            # set as default if not required and not supplied
            else:
                j_args['cabinet'][option] = requirements["default"]

        # ensure types are correct and values are allowed
        else:
            arg = j_args['cabinet'][option]
            if not isinstance(arg, requirements['type']):
                is_valid = False
                LOGGER.error(f"Invalid cabinet option: {option}. Must be of type {requirements['type']}")
            elif "values" in requirements:
                if arg not in requirements['values']:
                    is_valid = False
                    LOGGER.error(f"Invalid cabinet option: {option}. Must be in {requirements['values']}")

    # create log directory if set and not exists
    if j_args['cabinet']['log_directory'] != "":
        os.makedirs(j_args['cabinet']['log_directory'], exist_ok=True)
    
    return j_args, is_valid

def validate_stage(j_args, stage):
    """
    Validates a stage's options from the param json.
    :param j_args: dict, the parsed json.
    :returns j_args: dict, the parsed json with any missing arguments set to default values
    :returns is_valid: bool, if the json is valid
    """
    is_valid = True
    container_type = j_args['cabinet']['container_type']

    options = {
        "action": {
            "required": False,
            "type": str,
            "values": ['run', 'exec'],
            "default": 'run'
        },
        "positional_args": {
            "required": False,
            "type": list,
            "default": []
        },
        "flags": {
            "required": False,
            "type": dict,
            "default": {}
        },
        "container_args": {
            "required": False,
            "type": dict,
            "default": {}
        }
    }

    if container_type == "singularity":
        options["container_filepath"] = {
            "required": True,
            "type": str
        }
        options["binds"] = {
            "required": False,
            "type": list,
            "default": {}
        }

    elif container_type == "docker":
        options["image_name"] = {
            "required": True,
            "type": str
        }
        options["mounts"] = {
            "required": False,
            "type": list,
            "default": {}
        }

    for option, requirements in options.items():
        # enforce required keys
        if option not in j_args['stages'][stage].keys():
            if requirements['required']:
                is_valid = False
                LOGGER.error(f"Missing required key in stage options: {stage}, {option}.")
                continue
            # set as default if not required and not supplied
            else:
                j_args['stages'][stage][option] = requirements["default"]

        # ensure types are correct and values are allowed
        else:
            arg = j_args['stages'][stage][option]
            if not isinstance(arg, requirements['type']):
                is_valid = False
                LOGGER.error(f"Invalid stage option: {stage}, {option}. Must be of type {requirements['type']}")
            elif "values" in requirements:
                if arg not in requirements['values']:
                    is_valid = False
                    LOGGER.error(f"Invalid stage option: {stage}, {option}. Must be in {requirements['values']}")

    if container_type == "singularity":
        if not os.path.isfile(j_args['stages'][stage]['container_filepath']):
            is_valid = False
            LOGGER.error(f"File does not exist at {j_args['stages'][stage]['container_filepath']}")
    
    return j_args, is_valid

def validate_binds(stage, j_args, type):
    """
    Validate binds or mounts for a specific stage.
    :param stage: str, name of the stage to validate
    :param j_args: dict, the parsed json.
    :param type: str, 'binds' or 'mounts'
    :return: is_valid, bool. whether the binds for this stage are valid
    """
    is_valid = True
    
    for binds in j_args['stages'][stage][type]:
        if 'host_path' not in binds.keys() or 'container_path' not in binds.keys():
            LOGGER.error(f"Invalid bind in {stage}. 'host_path' and 'container_path' are required for all binds.")
            is_valid = False
        if not os.path.exists(binds['host_path']):
            if j_args["cabinet"]["handle_missing_host_paths"] == 'stop':
                LOGGER.error(f"Host filepath in stage {stage} does not exist: {binds['host_path']}")
                is_valid = False
            elif j_args["cabinet"]["handle_missing_host_paths"] == 'make_directories':
                os.makedirs(binds["host_path"])
                LOGGER.info(f"Made directory {binds['host_path']}")

    return is_valid