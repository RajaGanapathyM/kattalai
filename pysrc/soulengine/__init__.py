from __future__ import annotations
import asyncio
import os
import sys
from datetime import datetime
from typing import Optional
import logging
import json
from importlib import reload
try:
    
    import torch
    _torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    print("Torch Lib:",_torch_lib)
    if os.path.exists(_torch_lib):
        os.add_dll_directory(_torch_lib)
    reload(torch)
    
except Exception  as e:
    print(str(e))
    
from .soulengine import *