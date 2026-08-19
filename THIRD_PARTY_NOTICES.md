# Third-Party Notices

DROID+ is licensed under the Apache License, Version 2.0. This file records
third-party software and other materials referenced by, imported by, or bundled
with the source tree.

Python package dependencies are installed by users from upstream package indexes
at install time. They are not redistributed with the DROID+ source release unless
explicitly noted below.

## Python Dependencies

The versions below are the reference versions reviewed for this release. They
are not additional package pins: the supported constraints remain those in
`pyproject.toml`, and installers may resolve a later compatible release.

| Project | Reviewed version | Use | Source | License |
| --- | --- | --- | --- | --- |
| fastapi | 0.128.0 | HTTP services | [fastapi/fastapi](https://github.com/fastapi/fastapi) | [MIT](https://github.com/fastapi/fastapi/blob/0.128.0/LICENSE) |
| uvicorn | 0.40.0 | ASGI server | [encode/uvicorn](https://github.com/encode/uvicorn) | [BSD-3-Clause](https://github.com/encode/uvicorn/blob/0.40.0/LICENSE.md) |
| pydantic | 2.12.5 | API models and validation | [pydantic/pydantic](https://github.com/pydantic/pydantic) | [MIT](https://github.com/pydantic/pydantic/blob/v2.12.5/LICENSE) |
| requests | 2.32.5 | HTTP clients | [psf/requests](https://github.com/psf/requests) | [Apache-2.0](https://github.com/psf/requests/blob/v2.32.5/LICENSE); [NOTICE](https://github.com/psf/requests/blob/v2.32.5/NOTICE) |
| numpy | 2.2.6 | Numeric arrays and image data | [numpy/numpy](https://github.com/numpy/numpy) | [BSD-3-Clause core](https://github.com/numpy/numpy/blob/v2.2.6/LICENSE.txt); [bundled-source notices](https://github.com/numpy/numpy/blob/v2.2.6/LICENSES_bundled.txt) |
| scipy | 1.15.3 | Geometry and interpolation utilities | [scipy/scipy](https://github.com/scipy/scipy) | [BSD-3-Clause core](https://github.com/scipy/scipy/blob/v1.15.3/LICENSE.txt); [bundled-source notices](https://github.com/scipy/scipy/blob/v1.15.3/LICENSES_bundled.txt) |
| opencv-python | 4.13.0.90 | Image I/O and video/image processing | [opencv/opencv-python](https://github.com/opencv/opencv-python) | [MIT wrapper and Apache-2.0 OpenCV](https://github.com/opencv/opencv-python/blob/90/LICENSE.txt); [wheel notices](https://github.com/opencv/opencv-python/blob/90/LICENSE-3RD-PARTY.txt) |
| pyarrow | 23.0.0 | Parquet export | [apache/arrow](https://github.com/apache/arrow/tree/apache-arrow-23.0.0) | [Apache-2.0](https://github.com/apache/arrow/blob/apache-arrow-23.0.0/LICENSE.txt); [NOTICE](https://github.com/apache/arrow/blob/apache-arrow-23.0.0/NOTICE.txt) |
| tqdm | 4.67.3 | Progress reporting | [tqdm/tqdm](https://github.com/tqdm/tqdm) | [MPL-2.0 AND MIT](https://github.com/tqdm/tqdm/blob/v4.67.3/LICENCE) |
| pyrobotiqgripper | 1.0.1 | Robotiq gripper control | [castetsb/pyRobotiqGripper](https://github.com/castetsb/pyRobotiqGripper) | [MIT](https://github.com/castetsb/pyRobotiqGripper/blob/master/LICENSE) |
| minimalmodbus | 2.1.1 | Robotiq serial/Modbus dependency | [pyhys/minimalmodbus](https://github.com/pyhys/minimalmodbus) | [Apache-2.0](https://github.com/pyhys/minimalmodbus/blob/2.1.1/LICENSE) |
| pyserial | 3.5 | Serial communication | [pyserial/pyserial](https://github.com/pyserial/pyserial) | [BSD-3-Clause](https://github.com/pyserial/pyserial/blob/v3.5/LICENSE.txt) |
| openpi-client | 0.1.2 | Pi0 / Pi0.5 policy websocket client | [Physical-Intelligence/openpi](https://github.com/Physical-Intelligence/openpi) | [Apache-2.0](https://github.com/Physical-Intelligence/openpi/blob/main/LICENSE) |
| Pillow | 9.0.1 | Image resizing helpers for policy observations | [python-pillow/Pillow](https://github.com/python-pillow/Pillow) | [HPND](https://github.com/python-pillow/Pillow/blob/9.0.1/LICENSE) |
| matplotlib | 3.10.9 | Optional analysis and plotting | [matplotlib/matplotlib](https://github.com/matplotlib/matplotlib) | [Matplotlib license (PSF-based)](https://github.com/matplotlib/matplotlib/blob/v3.10.9/LICENSE/LICENSE) |
| pin (Pinocchio) | 4.0.0 | Optional kinematics analysis | [stack-of-tasks/pinocchio](https://github.com/stack-of-tasks/pinocchio) | [BSD-2-Clause upstream](https://github.com/stack-of-tasks/pinocchio/blob/v4.0.0/LICENSE); [PyPI package metadata lists BSD-3-Clause](https://pypi.org/project/pin/4.0.0/) |
| websockets | 16.0 | Optional DreamZero policy transport | [python-websockets/websockets](https://github.com/python-websockets/websockets) | [BSD-3-Clause](https://github.com/python-websockets/websockets/blob/16.0/LICENSE) |
| msgpack | 1.2.1 | Optional DreamZero message serialization | [msgpack/msgpack-python](https://github.com/msgpack/msgpack-python) | [Apache-2.0](https://github.com/msgpack/msgpack-python/blob/v1.2.1/COPYING) |
| lerobot | 0.4.3 | Optional SO-101 teleoperation and Hugging Face dataset push path | [huggingface/lerobot](https://github.com/huggingface/lerobot) | [Apache-2.0 AND MIT](https://github.com/huggingface/lerobot/blob/v0.4.3/LICENSE) |

Copyright and attribution notices are maintained in the linked upstream license
files. These packages and their transitive dependencies are installed separately
by users and are not copied into the DROID+ source distribution. Any notices
bundled in an installed wheel remain part of that upstream package.

### Primary Copyright and Attribution Notices

- FastAPI: `Copyright (c) 2018 Sebastián Ramírez`.
- Uvicorn: `Copyright © 2017-present, Encode OSS Ltd. All rights reserved.`
- Pydantic: `Copyright (c) 2017 to present Pydantic Services Inc. and individual contributors.`
- Requests: `Requests` / `Copyright 2019 Kenneth Reitz`.
- NumPy: `Copyright (c) 2005-2024, NumPy Developers. All rights reserved.`
- SciPy: `Copyright (c) 2001-2002 Enthought, Inc. 2003-2024, SciPy Developers. All rights reserved.`
- opencv-python wrapper: `Copyright (c) Olli-Pekka Heinisuo`.
- Apache Arrow: `Copyright 2016-2024 The Apache Software Foundation`.
- tqdm: `MPL-2.0 2015-2026 (c) Casper da Costa-Luis`; `MIT 2016 (c) [PR #96] on behalf of Google Inc.`; and `MIT 2013 (c) Noam Yorav-Raphael, original author.`
- pyrobotiqgripper: `Copyright (c) [2024] [Benoit CASTETS]`.
- MinimalModbus: `Copyright 2023 Jonas Berg`.
- pyserial: `Copyright (c) 2001-2020 Chris Liechti <cliechti@gmx.net>` / `All Rights Reserved.`
- Pillow/PIL: `Copyright © 1997-2011 by Secret Labs AB`; `Copyright © 1995-2011 by Fredrik Lundh`; and `Copyright © 2010-2022 by Alex Clark and contributors`.
- Matplotlib: `Copyright (c) 2012- Matplotlib Development Team; All Rights Reserved`; historical code also carries `Copyright (c) 2002-2011 John D. Hunter; All Rights Reserved`.
- Pinocchio: `Copyright (c) 2014-2023, CNRS` and `Copyright (c) 2018-2025, INRIA`.
- websockets: `Copyright (c) Aymeric Augustin and contributors`.
- msgpack: `Copyright (C) 2008-2011 INADA Naoki <songofacandy@gmail.com>`.
- LeRobot: `Copyright 2024 The Hugging Face team. All rights reserved.` Its linked license contains additional MIT-derived-code notices that must be retained with redistributed LeRobot code.

### Legal Review Notes

- The `pin` PyPI metadata says `BSD-3-Clause`, while the corresponding
  Pinocchio 4.0.0 upstream source is `BSD-2-Clause`.
- NumPy, SciPy, opencv-python, Pillow, Matplotlib, and LeRobot wheels contain
  additional platform- or component-specific notices. DROID+ does not
  redistribute those wheels; inspect the exact artifacts if a future container,
  environment, or binary bundle includes them.

## Separately Obtained Integration Software

### franky-control

DROID+ contains an integration with `franky-control`, but does not distribute,
bundle, declare as a package dependency, or automatically install it. Users who
enable the Franka robot-control service must obtain it separately from the
[upstream project](https://github.com/TimSchneider42/franky).

- Version reviewed: 1.1.3
- License file: [LGPL-3.0-or-later](https://github.com/TimSchneider42/franky/blob/v1.1.3/LICENSE)
- Upstream terms note: the upstream README describes the LGPL as applying to
  non-commercial applications and requests a separate agreement for commercial
  use. This conflicts with normal LGPL commercial-use rights.

Users must review and comply with the upstream terms. NVIDIA does not grant any
rights to `franky-control`. NVIDIA Legal confirmation is required before relying
on this integration for NVIDIA commercial use or representing it as a cleared
dependency of the DROID+ release.

## Bundled and Derived Source Code

### Fairo / Polymetis Robotiq meshes

DROID+ redistributes the following Robotiq 2F-85 mesh files from
[Fairo / Polymetis](https://github.com/facebookresearch/fairo):

- `droid_plus/assets/franka_robotiq_85/meshes/robotiq-2f/visual/base.stl`
- `droid_plus/assets/franka_robotiq_85/meshes/robotiq-2f/visual/coupler.stl`
- `droid_plus/assets/franka_robotiq_85/meshes/robotiq-2f/visual/driver.stl`
- `droid_plus/assets/franka_robotiq_85/meshes/robotiq-2f/visual/follower.stl`
- `droid_plus/assets/franka_robotiq_85/meshes/robotiq-2f/visual/pad.stl`
- `droid_plus/assets/franka_robotiq_85/meshes/robotiq-2f/visual/spring_link.stl`

The files are byte-for-byte identical to the files in Fairo at
`polymetis/polymetis/data/kuka_iiwa/meshes/robotiq-2f/collision/`.
Fairo's `franka_panda_robotiq_85` model references that shared mesh directory
through a symbolic link.

- Upstream model: https://github.com/facebookresearch/fairo/tree/main/polymetis/polymetis/data/franka_panda_robotiq_85
- Upstream mesh directory: https://github.com/facebookresearch/fairo/tree/main/polymetis/polymetis/data/kuka_iiwa/meshes/robotiq-2f/collision
- License: MIT

Copyright (c) Facebook, Inc. and its affiliates.

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

### OpenPI / openpi-client

`droid_plus/policies/image_tools.py` contains image conversion and padded-resize
implementations derived from `openpi_client.image_tools`. The code reached
DROID+ through NVIDIA RoboLab's image utilities and remains semantically
equivalent to the OpenPI implementation.

- Upstream project: https://github.com/Physical-Intelligence/openpi
- Upstream source: `packages/openpi-client/src/openpi_client/image_tools.py`
- License: Apache License 2.0

The Apache License 2.0 text distributed in `LICENSE` is the applicable license
text for this bundled code.

### NVIDIA RoboLab

The following NVIDIA-authored code was reused or adapted from RoboLab:

- `droid_plus/eval/base_client.py` is a copy of
  `robolab/eval/base_client.py`.
- `droid_plus/policies/dreamzero.py` is adapted from RoboLab's former
  `robolab_policy_client/dreamzero.py`, now located at
  `policies/dreamzero/client.py`.
- `droid_plus/policies/runtime.py` is adapted from RoboLab's former
  `robolab_policy_client/runtime.py`.

RoboLab is available at https://github.com/NVlabs/RoboLab under the Apache
License 2.0. The current corresponding image utility is
`robolab/core/utils/image_utils.py`.

### DreamZero

`droid_plus/policies/dreamzero.py` implements the DreamZero/RoboArena wire
protocol through the NVIDIA RoboLab client lineage. DROID+ does not bundle
DreamZero model code, model weights, or checkpoints.

- Upstream project: https://github.com/dreamzero0/dreamzero
- License: Apache License 2.0

## External Tools and SDKs

| Project | Use | License / Notes |
| --- | --- | --- |
| ffmpeg | User-installed video encoding for video and LeRobot dataset export | Not distributed with DROID+; license depends on the user's ffmpeg build (commonly LGPL with optional GPL components) |
| ZED SDK / pyzed | ZED camera access | User-installed Stereolabs SDK; not distributed with DROID+ |

## Video and Codec Functionality

DROID+ source code can invoke user-installed OpenCV and ffmpeg tooling to write
camera recordings and LeRobot dataset videos. DROID+ does not install or
distribute ffmpeg, codec object code, or codec binaries.
