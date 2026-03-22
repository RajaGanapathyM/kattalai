from __future__ import annotations
import asyncio
import os
import sys
from datetime import datetime
from typing import Optional
import logging
import json
try:
    _torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    print("Torch Lib:",_torch_lib)
    if os.path.exists(_torch_lib):
        os.add_dll_directory(_torch_lib)
    import torch
    
except Exception  as e:
    print(str(e))
    
from .soulengine import *