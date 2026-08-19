# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
ROOT_DIR=~/droid-plus

go_cameras() {
    source $ROOT_DIR/venv/bin/activate
    cd $ROOT_DIR
    make camera_service
}

go_gripper() {
    source $ROOT_DIR/venv/bin/activate
    cd $ROOT_DIR
    make gripper_service
}

go_franky() {
    source $ROOT_DIR/venv/bin/activate
    cd $ROOT_DIR
    make franky_service
}

go() {
    source $ROOT_DIR/venv/bin/activate
    cd $ROOT_DIR
}
