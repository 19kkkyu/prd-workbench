import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from workbench.config import ROOT,setting
from workbench.intelligence.pipeline import timestamp
from workbench.storage.schema import validate_run


class LocalStore:
    def __init__(self,directory=None):
        self.root=Path(directory or setting('DATA_DIR','data'))
        if not self.root.is_absolute():self.root=ROOT/self.root
        self.root.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS summaries(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
              created TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calls(day TEXT PRIMARY KEY,count INTEGER NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.root/'summaries.sqlite3',timeout=30)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:db.close()

    def create_project(self,name):
        name=name.strip()
        if not name or len(name)>100:raise ValueError('项目名需为 1—100 个字符。')
        project={'id':str(uuid.uuid4()),'name':name,'created':timestamp()}
        with self.db() as db:
            db.execute('INSERT INTO projects VALUES(?,?,?)',tuple(project.values()))
        return project

    def projects(self):
        with self.db() as db:return [dict(r) for r in db.execute('SELECT * FROM projects ORDER BY created DESC,id DESC')]

    def save(self,run):
        run=validate_run(run)
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO summaries VALUES(?,?,?,?)',(run['id'],run['project_id'],run['created'],json.dumps(run,ensure_ascii=False)))

    def runs(self,project_id=None):
        with self.db() as db:
            rows=db.execute('SELECT payload FROM summaries '+('WHERE project_id=? ' if project_id else '')+'ORDER BY created DESC,id DESC',
                (project_id,) if project_id else ()).fetchall()
        return [json.loads(r[0]) for r in rows]

    def delete_run(self,run_id):
        with self.db() as db:db.execute('DELETE FROM summaries WHERE id=?',(run_id,))

    def rename_project(self,project_id,name):
        name=name.strip()
        if not name or len(name)>100:raise ValueError('项目名需为 1—100 个字符。')
        with self.db() as db:db.execute('UPDATE projects SET name=? WHERE id=?',(name,project_id))

    def delete_project(self,project_id):
        with self.db() as db:db.execute('DELETE FROM projects WHERE id=?',(project_id,))

    def reserve_call(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            day=timestamp()[:10]
            db.execute('INSERT OR IGNORE INTO calls VALUES(?,0)',(day,))
            count=db.execute('SELECT count FROM calls WHERE day=?',(day,)).fetchone()[0]
            if count>=int(setting('DAILY_CALL_LIMIT','150')):raise ValueError('已达到今日调用上限。')
            db.execute('UPDATE calls SET count=count+1 WHERE day=?',(day,))
