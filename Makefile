# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
PYTHON ?= python3
FRANKY_SERVICE_URL ?= $(shell $(PYTHON) -c "from droid_plus.constants import FRANKY_SERVICE_URL; print(FRANKY_SERVICE_URL)")
GRIPPER_SERVICE_URL ?= $(shell $(PYTHON) -c "from droid_plus.constants import GRIPPER_SERVICE_URL; print(GRIPPER_SERVICE_URL)")
INSTRUCTION ?=
NOTES ?=
FPS ?= 10
RUN_DIR ?=

.PHONY: setup_zed drop open close home stop reset run_policy run_policy_record video export_parquet export_lerobot install install-dev

# --- Installation ---
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

install-all:
	pip install -e ".[all]"

# --- ZED Setup ---
setup_zed:
	$(PYTHON) /usr/local/zed/get_python_api.py
	$(PYTHON) -c "import pyzed.sl as sl; print('OK', sl.__version__ if hasattr(sl,'__version__') else 'loaded')"

# --- Gripper Commands ---
drop:
	$(PYTHON) -m droid_plus.services.gripper_client

open:
	curl -sS -X POST $(GRIPPER_SERVICE_URL)/open

close:
	curl -sS -X POST $(GRIPPER_SERVICE_URL)/close

# --- Robot Commands ---
home:
	curl -X POST $(FRANKY_SERVICE_URL)/go_home

stop:
	curl -X POST $(FRANKY_SERVICE_URL)/stop

reset:
	$(MAKE) stop
	$(MAKE) home
	sleep 3
	$(MAKE) stop
	$(MAKE) drop

# --- Policy Experiments ---
run_policy_inf:
	$(PYTHON) scripts/run_experiment_cli.py --instruction "$(INSTRUCTION)"

run_policy_record_inf:
	$(PYTHON) scripts/run_experiment_cli.py --instruction "$(INSTRUCTION)" --record

run_policy_record_450:
	$(PYTHON) scripts/run_experiment_cli.py --instruction "$(INSTRUCTION)" --record --action-step-limit 450

# Record with a free-form note string attached to the episode metadata.
# Usage:
#   make run_experiment_450 INSTRUCTION="pick up the tape" NOTES="exp42: new grasp, lighting A"
run_experiment_450:
	$(PYTHON) scripts/run_experiment_cli.py --instruction "$(INSTRUCTION)" --record --action-step-limit 450 --notes "$(NOTES)"

run_experiment_900:
	$(PYTHON) scripts/run_experiment_cli.py --instruction "$(INSTRUCTION)" --record --action-step-limit 900 --notes "$(NOTES)"


# --- Data Export ---
# Export a recorded run's JSONL steps into Parquet.
# Usage:
#   make export_parquet RUN_DIR=output/FoodPacking_pi0_20260106_123456
#   make export_parquet RUN_DIR=output/FoodPacking_pi0_20260106_123456/episode_000
export_parquet:
	@test -n "$(RUN_DIR)" || (echo "ERROR: set RUN_DIR=... (run dir or episode dir)" && exit 2)
	$(PYTHON) -m droid_plus.logging.export_parquet "$(RUN_DIR)"

# Export a recorded run to local LeRobot v2.1 dataset format (parquet + mp4 + meta).
#
# Usage:
#   make export_lerobot RUN_DIR=output/FoodPacking_pi0_20260106_123456
#   make export_lerobot RUN_DIR=output/run OUT_DIR=output/lerobot/run OVERWRITE=1
#   make export_lerobot RUN_DIR=output/run PUSH=hugo/foodpacking PRIVATE=1
OUT_DIR ?=
PUSH ?=
PRIVATE ?=
OVERWRITE ?=
export_lerobot:
	@test -n "$(RUN_DIR)" || (echo "ERROR: set RUN_DIR=... (run dir)" && exit 2)
	@command -v ffmpeg >/dev/null 2>&1 || (echo "ERROR: ffmpeg not found in PATH" && exit 2)
	$(PYTHON) scripts/export_lerobot.py "$(RUN_DIR)" \
	  $(if $(OUT_DIR),--out-dir "$(OUT_DIR)") \
	  $(if $(OVERWRITE),--overwrite) \
	  $(if $(PUSH),--push "$(PUSH)") \
	  $(if $(PRIVATE),--private)

# Convert a recorded run's per-camera frame directories into mp4 using ffmpeg.
# Usage:
#   make video RUN_DIR=output/FoodPacking_pi0_20260106_123456
#   make video RUN_DIR=output/FoodPacking_pi0_20260106_123456/episode_000 FPS=10
video:
	@test -n "$(RUN_DIR)" || (echo "ERROR: set RUN_DIR=... (run dir or episode dir)" && exit 2)
	@command -v ffmpeg >/dev/null 2>&1 || (echo "ERROR: ffmpeg not found in PATH" && exit 2)
	@set -e; \
	base="$(RUN_DIR)"; \
	if [ -d "$$base/episode_000" ] || ls "$$base"/episode_* >/dev/null 2>&1; then \
	  episodes=$$(ls -d "$$base"/episode_* 2>/dev/null | sort); \
	else \
	  episodes="$$base"; \
	fi; \
	for ep in $$episodes; do \
	  echo "==> $$ep"; \
	  for cam in left wrist; do \
	    if [ -d "$$ep/$$cam" ] && ls "$$ep/$$cam"/000000000.jpg >/dev/null 2>&1; then \
	      out="$$ep/$$cam.mp4"; \
	      echo "  ffmpeg $$cam -> $${out##*/} (FPS=$(FPS))"; \
	      ffmpeg -y -loglevel error -framerate "$(FPS)" -i "$$ep/$$cam/%09d.jpg" -c:v libx264 -pix_fmt yuv420p "$$out"; \
	    else \
	      echo "  skip $$cam (no frames)"; \
	    fi; \
	  done; \
	done

# --- Services ---
franky_service:
	uvicorn droid_plus.services.franky_service:app --host 0.0.0.0 --port 54321 --workers 1

camera_service:
	ZED_CAMERA_RESOLUTION=$${ZED_CAMERA_RESOLUTION:-VGA} uvicorn droid_plus.services.camera_service:app --host 0.0.0.0 --port 54322 --workers 1 --no-access-log

realsense_camera_service:
	uvicorn droid_plus.services.realsense_camera_service:app --host 0.0.0.0 --port 54322 --workers 1 --no-access-log

gripper_service:
	uvicorn droid_plus.services.gripper_service:app --host 0.0.0.0 --port 54323 --workers 1

# --- Analysis ---
summarize:
	$(PYTHON) scripts/summarize_results.py

summarize_task:
	$(PYTHON) scripts/summarize_results.py --task "$(TASK)"
