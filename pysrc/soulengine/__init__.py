from __future__ import annotations
import os
import sys

torch_lib1 = os.path.join(sys.prefix, "Lib", "site-packages", "torch", "lib")

torch_lib2 = os.path.join(
    sys.prefix, "Lib", "site-packages", "torch", "lib"
)

for path in [torch_lib1, torch_lib2]:
    if os.path.exists(path):
        os.add_dll_directory(path)

import torch

print("Torch loaded from:", torch.__file__)

# NOW safe
from .soulengine import *