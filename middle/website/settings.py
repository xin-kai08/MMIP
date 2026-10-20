from dataclasses import dataclass, field
from pathlib import Path
import json
import os

ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Settings:
    root: Path = ROOT
    values: dict = field(default_factory=dict)

    def __post_init__(self):
        base = json.loads((ROOT/'website/config.json').read_text('utf-8'))
        base.update(self.values)
        for key in ('model_path','device','database','uploads'):
            if value := os.environ.get('WASTE_'+key.upper()):base[key]=value
        self.values=base
        if not 1<=base['max_files']<=20:raise ValueError('max_files must be between 1 and 20')
        if not set(base['formats']) <= {'JPEG','PNG','WEBP'}:raise ValueError('Unsupported image format in settings')
        if base['max_file_bytes']<=0 or base['max_pixels']<=0:raise ValueError('Invalid upload limit')
        for key in ('uploads','database'):
            target=(self.root/base[key]).resolve()
            if target.is_relative_to((ROOT/'dataset').resolve()) or target.is_relative_to((ROOT/'training').resolve()):
                raise ValueError('Website storage must be separate from dataset and training')

    def __getattr__(self,key):
        if key in self.values:return self.values[key]
        raise AttributeError(key)

    def path(self,key):return (self.root/self.values[key]).resolve()

    @property
    def dist(self):return ROOT/'website/frontend/dist'

    @property
    def max_body(self):return self.max_files*self.max_file_bytes+1024*1024
