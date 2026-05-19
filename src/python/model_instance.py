from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ModelInstance:

    model: str
    name: str
    repo_name: str
    
    basefile: Optional[str] = None

    config_dir: Optional[Path] = None

    outputs_dir: Optional[Path] = None

    exe_dir: Optional[Path] = None
        
    def is_variant(self):
        return self.name.lower() != self.model.lower()
