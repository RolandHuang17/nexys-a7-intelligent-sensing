"""Atomic, recoverable saves. Practice and physical-board records are separate."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
import shutil
import uuid


DEFAULTS = {'version':1, 'settings':{'sensitivity':18, 'effects':True, 'sound':True},
            'board':{}, 'keyboard':{}}


class SaveStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory/'progress.json'
        self.warning = ''
        self.data = deepcopy(DEFAULTS)
        for source in (self.path, self.path.with_suffix('.bak')):
            try:
                value = json.loads(source.read_text(encoding='utf8'))
                self._validate(value)
                self.data = value
                if source != self.path:
                    self.warning = '存档已从上一次备份恢复。'
                break
            except FileNotFoundError:
                continue
            except (ValueError, TypeError, KeyError, OSError):
                self.warning = '存档无法读取，已使用备份或新建进度；原件仍保留。'

    @staticmethod
    def _validate(value):
        if not isinstance(value,dict) or value.get('version') != 1:
            raise ValueError('unsupported save')
        settings=value['settings']
        if settings['sensitivity'] not in (12,18,24):
            raise ValueError('sensitivity')
        if any(type(settings[k]) is not bool for k in ('effects','sound')):
            raise ValueError('settings')
        for mode in ('board','keyboard'):
            if not isinstance(value[mode],dict):
                raise ValueError('records')
            for key,row in value[mode].items():
                if str(int(key)) != key or not 1 <= int(key) <= 8:
                    raise ValueError('level')
                if type(row['stars']) is not int or not 1 <= row['stars'] <= 3:
                    raise ValueError('stars')
                if not isinstance(row['best_seconds'],(int,float)) or not math.isfinite(row['best_seconds']) or row['best_seconds'] < 0:
                    raise ValueError('time')

    def commit(self):
        self._validate(self.data)
        self.directory.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_name('progress.'+uuid.uuid4().hex+'.tmp')
        try:
            with temp.open('w',encoding='utf8') as f:
                json.dump(self.data,f,ensure_ascii=False,indent=2)
                f.flush()
                os.fsync(f.fileno())
            if self.path.exists():
                try:
                    self._validate(json.loads(self.path.read_text(encoding='utf8')))
                    shutil.copy2(self.path,self.path.with_suffix('.bak'))
                except (ValueError,TypeError,KeyError):
                    pass  # Never replace a valid backup with a corrupt save.
            os.replace(temp,self.path)
        finally:
            temp.unlink(missing_ok=True)

    def record(self, mode, result):
        if mode not in ('board','keyboard') or not result['won']:
            raise ValueError('only completed games may be saved')
        key=str(result['level'])
        previous=self.data[mode].get(key,{})
        self.data[mode][key]={'stars':max(result['stars'],previous.get('stars',0)),
                              'best_seconds':min(result['seconds'],previous.get('best_seconds',float('inf'))),
                              'last_result':result,
                              'updated':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')}
        self.commit()

    def unlocked(self, mode):
        if mode == 'keyboard':
            return 8  # Practice can inspect every course, without unlocking board records.
        unlocked=1
        while str(unlocked) in self.data['board'] and unlocked < 8:
            unlocked += 1
        return unlocked

    def total_stars(self, mode):
        return sum(r['stars'] for r in self.data[mode].values())
