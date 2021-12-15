#!/usr/bin/env python3
# coding: utf-8

"""
CABINET
Created: 2021-11-12
Updated: 2021-12-02
"""

# Import standard libraries
import argparse
from datetime import datetime
from glob import glob
import math
from nipype.interfaces import fsl
import os
import pandas as pd
import random
import shutil
import subprocess
import sys


def find_myself(flg):
    """
    Ensure that this script can find its dependencies if parallel processing
    :param flg: String in sys.argv immediately preceding the path to return
    :return: String, path to the directory this Python script is in
    """
    try:
        parallel_flag_pos = -2 if sys.argv[-2] == flg else sys.argv.index(flg)
        sys.path.append(os.path.abspath(sys.argv[parallel_flag_pos + 1]))
    except (IndexError, ValueError):
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    return sys.path[-1]


# Constants: Paths to this dir and level 1 analysis script
WRAPPER_LOC = '--wrapper-location'
SCRIPT_DIR = find_myself(WRAPPER_LOC)
STAGES = ("crop-resize", "nnU-Net", "chirality-mask", "nibabies", "XCP")  # Call "crop_resize" Pre-BIBS-Net and "chirality-mask" Post-BIBS-Net?

# Custom local imports
from src.utilities import (
    as_cli_arg, crop_images, ensure_dict_has, exit_with_time_info, extract_from_json, resize_images,
    valid_readable_json
)


def main():
    # Time how long the script takes and get command-line arguments from user 
    start = datetime.now()
    json_args = get_params_from_JSON()

    print(json_args)  # TODO REMOVE LINE

    # Run nnU-Net
    json_args = crop_and_resize_images(json_args)  # Somebody else already writing this (Paul?)
    if json_args["nibabies"]["age_months"] <= 8:
        json_args = copy_images_to_nnUNet_dir(json_args)  # TODO
        segmentation = un_nnUNet_predict(json_args)
        segmentation = ensure_chirality_flipped(segmentation)  # Paul(?) already writing this

    # Put just the mask and the segmentation (and nothing else) into a directory to run nibabies
        mask = make_mask(json_args, segmentation)  # Luci has a script for this - we'll just use it as a blueprint
        run_nibabies(json_args, mask, segmentation)
    else:
        run_nibabies(json_args)

    # Show user how long the pipeline took and end the pipeline here
    exit_with_time_info(start)


def get_params_from_JSON():
    """
    :return: Dictionary containing all parameters from parameter .JSON file
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "parameter_json", type=valid_readable_json,
        help=("Valid path to readable parameter .json file. See README.md "
              "for more information on parameters")
        # TODO: Add description of every parameter to the README, and maybe also to this --help message
        # TODO: Add nnU-Net parameters (once they're decided on)
        # TODO: Maaaybe read in each parameter from the .json using argparse if possible? stackoverflow.com/a/61003775
    )
    parser.add_argument(
        "stages", nargs="+", required=True, choices=STAGES, default=STAGES
    )
    return validate_json_args(extract_from_json(parser.parse_args().parameter_json), parser)


def validate_json_args(j_args):
    """
    :param j_args: Dictionary containing all args from parameter .JSON file
    """
    # TODO Validate types in j_args; e.g. validate that nibabies[age_months] is an int

    j_args["nibabies"] = ensure_dict_has(
        j_args["nibabies"], "age_months",
        read_age_from_participants_tsv(j_args)
        # TODO Figure out which column in the participants.tsv file has the age_months value
    )


def read_age_from_participants_tsv(j_args):
    """
    :param j_args: Dictionary containing all args from parameter .JSON file
    :return: Int, the subject's age (in months) listed in participants.tsv
    """
    # Read in participants.tsv
    part_tsv_df = pd.read_csv(os.path.join(j_args["common"]["bids_dir"],
                                           "participants.tsv"), sep="\t")

    # Column names of participants.tsv                         
    age_months_col = "age" # TODO Get name of column with age_months value
    sub_ID_col = "participant_id" # TODO Figure out the subject ID column name (participant ID or subject ID)
    ses_ID_col = "session"

    # Ensure that the subject and session IDs start with the right prefixes
    sub_ses = {"participant_label": "sub-", "session": "ses-"}
    for param_name, prefix in sub_ses.items():
        param = j_args["common"][param_name]
        sub_ses[prefix] = (param if param[:len(prefix)]
                            == prefix else prefix + param)

    # Get and return the age_months value from participants.tsv
    subj_row = part_tsv_df.loc[(part_tsv_df[sub_ID_col] == sub_ses["sub-"]) &
                               (part_tsv_df[ses_ID_col] == sub_ses["ses-"])] # select where "participant_id" and "session" match

    return int(subj_row.loc[age_months_col].strip("M")) # the "age" column has an "M" at the end of each number


def crop_and_resize_images(j_args):
    """
    :param j_args: Dictionary containing all args from parameter .JSON file
    """
    crop_images(j_args["crop_resize"]["input_dir"],
                j_args["crop_resize"]["output_dir"])
    resize_images(j_args["crop_resize"]["input_dir"],
                  j_args["crop_resize"]["output_dir"])


def make_mask(j_args):
    """
    :param j_args: Dictionary containing all args from parameter .JSON file
    """
    base_dir = j_args["nibabies"]["work_dir"]
    os.chdir(base_dir)
    
    aseg = glob('sub-*_aseg.nii.gz')
    aseg.sort()

    aseg_spec = dict()
    for specifier in ("temp", "sub", "ses"):
        aseg_spec[specifier] = list()
        for i in range(len(aseg)):
            aseg_spec[specifier].append(aseg[i])

    # Step 1: Dilate aseg to make mask
    op_strings = ['{}-ero'.format(xtra) for xtra in
                  ('', '-bin -dilM -dilM -dilM -dilM -fillh -ero -ero ')]
    for sub, ses in zip(aseg_spec['sub'], aseg_spec['ses']):
        anatfiles = ['{}_{}_aseg{}.nii.gz'.format(sub, ses, uniq)
                     for uniq in ('', '_mask_dil', '_mask')]
        for i in range(1):
            img_maths = fsl.ImageMaths(in_file=anatfiles[i],
                                       out_file=anatfiles[i + 1],
                                       op_string=op_strings[i])
            img_maths.run()


def make_mask_Luci_original(j_args):
    """
    :param j_args: Dictionary containing all args from parameter .JSON file
    """
    base_dir = j_args["nibabies"]["work_dir"]
    os.chdir(base_dir)
    
    aseg = glob('sub-*_aseg.nii.gz')
    aseg.sort()

    temp = []
    for i in aseg:
        temp.append(i.split('_'))
    sub = []
    for i in range(len(temp)):
        sub.append(temp[i][0])
    ses = []
    for i in range(len(temp)):
        ses.append(temp[i][1])

    ##step 1: dilate aseg to make mask:
    for sub, ses in zip(sub, ses):
        anatfile = '{}_{}_aseg.nii.gz'.format(sub,ses)
        img_maths = fsl.ImageMaths(in_file=anatfile, op_string='-bin -dilM -dilM -dilM -dilM -fillh -ero -ero -ero',
                                   out_file='{}_{}_aseg_mask_dil.nii.gz'.format(sub,ses))
        img_maths.run()
    
        anatfile = '{}_{}_aseg_mask_dil.nii.gz'.format(sub, ses)
        img_maths = fsl.ImageMaths(in_file=anatfile, op_string='-ero',
                                   out_file='{}_{}_aseg_mask.nii.gz'.format(sub, ses))
        img_maths.run()


def run_nibabies(j_args):
    """
    :param j_args: Dictionary containing all args from parameter .JSON file
    """
    # Get nibabies options from parameter file and turn them into flags
    nibabies_args = list()
    for nibabies_arg in ["age_months", "work_dir", ]:
        nibabies_args.append(as_cli_arg(nibabies_arg))
        nibabies_args.append(j_args["nibabies"][nibabies_arg])

    # Get cohort number from template_description.json
    template_description = extract_from_json(j_args["common"]["template_description_json"])
    cohorts = template_description["cohort"]
    for cohort_num, cohort_details in cohorts:
        if (int(cohort_details["age"][0]) < int(j_args["nibabies"]["age_months"])
                                            < int(cohort_details["age"][1])):
            cohort = cohort_num
            break

    # Run nibabies
    myseg_dir = os.path.join(j_args["common"]["derivatives"], "myseg")
    subprocess.check_call([
        j_args["nibabies"]["script_path"],
        j_args["common"]["bids_dir"],
        j_args["common"]["nibabies_dir"],
        "participant",
        "--derivatives", myseg_dir,
        "--output-spaces", "MNIInfant:cohort-{}".format(cohort),
        *nibabies_args
    ])


if __name__ == '__main__':
    main()