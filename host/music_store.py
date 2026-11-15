"""Local music metadata, attempts and idempotent favourites; no cloud dependency."""
import contextlib,hashlib,json,sqlite3,unicodedata,uuid
from pathlib import Path
from audit import ROOT,now

def song_key(title,artist):
    text='\0'.join(unicodedata.normalize('NFKC',v).strip().casefold() for v in (title,artist))
    return hashlib.sha256(text.encode('utf8')).hexdigest()
class MusicStore:
    def __init__(self,folder=None):
        self.folder=Path(folder or ROOT/'music');self.folder.mkdir(parents=True,exist_ok=True);self.path=self.folder/'music.sqlite3'
        with self.db() as c:c.executescript('''
        CREATE TABLE IF NOT EXISTS songs(id TEXT PRIMARY KEY,title TEXT NOT NULL,artist TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS recordings(id TEXT PRIMARY KEY,song_id TEXT NOT NULL,original_sha256 TEXT NOT NULL,
          canonical_sha256 TEXT UNIQUE NOT NULL,file TEXT NOT NULL,duration REAL NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,song_id TEXT,source TEXT NOT NULL,
          mode TEXT NOT NULL,status TEXT NOT NULL,wav TEXT,wav_sha256 TEXT,details TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS favourites(song_id TEXT PRIMARY KEY,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS online_requests(id TEXT PRIMARY KEY,wav_sha256 TEXT NOT NULL,status TEXT NOT NULL,
          token TEXT,updated_at TEXT NOT NULL,details TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,details TEXT NOT NULL);
        ''')
    @contextlib.contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=20);c.row_factory=sqlite3.Row
        try:c.execute('PRAGMA journal_mode=WAL');yield c;c.commit()
        except: c.rollback();raise
        finally:c.close()
    def setting(self,key,default=None):
        with self.db() as c:r=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(r[0]) if r else default
    def set_setting(self,key,value):
        with self.db() as c:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))
    def put_song(self,title,artist):
        key=song_key(title,artist)
        with self.db() as c:c.execute('INSERT OR IGNORE INTO songs VALUES(?,?,?)',(key,title,artist))
        return key
    def recordings(self):
        with self.db() as c:return [dict(r) for r in c.execute('SELECT r.*,s.title,s.artist FROM recordings r JOIN songs s ON s.id=r.song_id ORDER BY r.created_at,r.id')]
    def record_result(self,job,result,mode,wav,wav_hash,details=None,update_pending=False):
        song=None
        if result.get('matched'):song=self.put_song(result['title'],result['artist'])
        payload={**(details or {}),**result}
        with self.db() as c:
            values=(job,result.get('recognized_at') or now(),song,result.get('source','none'),mode,'matched' if song else 'unmatched',str(wav),wav_hash,json.dumps(payload,ensure_ascii=False))
            c.execute('INSERT OR IGNORE INTO history VALUES(?,?,?,?,?,?,?,?,?)',values)
            if update_pending:
                c.execute('UPDATE history SET created_at=?,song_id=?,source=?,mode=?,status=?,wav=?,wav_sha256=?,details=? WHERE id=?',values[1:]+(job,))
        return song
    def pending_online(self):
        with self.db() as c:
            rows=c.execute("SELECT o.id,o.status,o.details,h.wav FROM online_requests o LEFT JOIN history h ON h.id=o.id WHERE o.status='submitted' AND o.token IS NOT NULL ORDER BY o.updated_at DESC")
            return [{'job_id':r['id'],'wav':r['wav'] or json.loads(r['details']).get('source_wav')} for r in rows]
    def favourite(self,song):
        if not song:return False
        with self.db() as c:
            if not c.execute('SELECT 1 FROM songs WHERE id=?',(song,)).fetchone():return False
            c.execute('INSERT OR IGNORE INTO favourites VALUES(?,?)',(song,now()))
        return True
    def history(self,*,text='',source='',start='',end='',favourites=False):
        sql='SELECT h.*,s.title,s.artist,f.created_at AS favourited_at FROM history h LEFT JOIN songs s ON s.id=h.song_id LEFT JOIN favourites f ON f.song_id=h.song_id WHERE 1=1';args=[]
        if text:sql+=' AND (s.title LIKE ? OR s.artist LIKE ?)';args += ['%'+text+'%']*2
        if source:sql+=' AND h.source=?';args.append(source)
        if start:sql+=' AND h.created_at>=?';args.append(start)
        if end:sql+=' AND h.created_at<?';args.append(end)
        if favourites:sql+=' AND f.song_id IS NOT NULL'
        with self.db() as c:rows=[dict(r) for r in c.execute(sql+' ORDER BY h.created_at DESC,h.id DESC',args)]
        for row in rows:row['details']=json.loads(row['details'])
        return rows
    def statistics(self,**filters):
        rows=self.history(**filters);groups={}
        for row in rows:
            if row['status']!='matched':continue
            g=groups.setdefault(row['song_id'],{'title':row['title'],'artist':row['artist'],'count':0,'times':[]});g['count']+=1;g['times'].append(row['created_at'])
        return sorted(groups.values(),key=lambda g:(-g['count'],g['title']))
    def online(self,identifier):
        with self.db() as c:r=c.execute('SELECT * FROM online_requests WHERE id=?',(identifier,)).fetchone()
        return dict(r) if r else None
    def save_online(self,identifier,wav_hash,status,*,token=None,details=None):
        with self.db() as c:c.execute('INSERT OR REPLACE INTO online_requests VALUES(?,?,?,?,?,?)',
            (identifier,wav_hash,status,token,now(),json.dumps(details or {},ensure_ascii=False)))
