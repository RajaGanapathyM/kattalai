"""
Claude Cowork — Terminal UI  v3
Tabs: Chat · Space · Agent Mind · Terminal
SoulEngine PyRuntime fully integrated with demo fallback.
"""

from __future__ import annotations
import asyncio
import os
import sys
from datetime import datetime
from typing import Optional
import logging
import json
try:
    import torch
    _torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
    if os.path.exists(_torch_lib):
        os.add_dll_directory(_torch_lib)
    
except Exception  as e:
    print(str(e))
    
from .soulengine import *