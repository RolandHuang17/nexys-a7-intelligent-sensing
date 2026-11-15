"""Reproducible publication figures from actual board event files."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from audit import ROOT,write_json,sha256
from features import load_event,independent_features
from experiment import decisions
from plot_style import apply,finish

PALETTE={'audio':'#2467a6','accel':'#cc7927','x':'#2467a6','y':'#9b7927','z':'#ad5686'}

def generate(collection,evaluation,report):
    collection=Path(collection);evaluation=Path(evaluation);report=Path(report)
    session=json.loads((collection/'session.json').read_text(encoding='utf8'))
    config=json.loads((collection/'frozen_config.json').read_text(encoding='utf8'))
    plt.rcParams.update({'font.family':'Microsoft YaHei','font.size':10,'axes.spines.top':False,
                         'axes.spines.right':False,'axes.unicode_minus':False,'pdf.fonttype':42})
    apply(plt)
    selected={label:next(t for t in session['trials'] if t['session']=='holdout' and t['label']==label) for label in ('tap','sound')}
    values={label:load_event(ROOT/trial['directory']) for label,trial in selected.items()}
    # Lock raw scales across the two comparable holdout figures.
    audio_extent=max(float(np.max(np.abs(v[1]))) for v in values.values())*1.08
    xyz_extent=max(float(np.max(np.abs(np.array(v[2])[:,1:]-np.mean(np.array(v[2])[:,1:],axis=0)))) for v in values.values())*1.08
    live=json.loads((collection/'live.json').read_text(encoding='utf8'))
    event=live['events'][0]
    selected['live']={'trial_id':'LIVE_online','directory':str((collection/'physical'/f'LIVE_event{event["event_id"]}').relative_to(ROOT))}
    values['live']=load_event(ROOT/selected['live']['directory'])
    index=[]
    for label,trial in selected.items():
        directory=ROOT/trial['directory'];meta,audio,xyz,first=values[label]
        features=independent_features(directory);ds=decisions(features,config['thresholds']['audio'],config['thresholds']['accel'],config['window_ms'])
        if label=='live':
            features=[{**r,'tick':r['tick']-meta['window_start'],
                       'joint':{'dedup':not r['joint_confirm']} if r['joint_pair'] else None} for r in live['rows']]
            ds=features
        ae=audio_extent if label!='live' else float(np.max(np.abs(audio)))*1.08
        xe=xyz_extent if label!='live' else float(np.max(np.abs(np.array(xyz)[:,1:]-np.mean(np.array(xyz)[:,1:],axis=0))))*1.08
        fig,axes=plt.subplots(4,1,figsize=(7.1,8.1),sharex=True,layout='constrained')
        t=(first+np.arange(len(audio))*6250-50000000)/1e8
        axes[0].plot(t,audio,color=PALETTE['audio'],linewidth=.6);axes[0].set_ylabel('PCM16\n计数');axes[0].set_ylim(-ae,ae)
        xyz=np.array(xyz);xt=(xyz[:,0]-50000000)/1e8
        for i,name in enumerate(('x','y','z')):
            axes[1].plot(xt,xyz[:,i+1]-xyz[:,i+1].mean(),label=name.upper(),color=PALETTE[name],linewidth=.9,linestyle=('-', '--',':')[i])
        axes[1].set_ylabel('XYZ 去均值\n标称 mg');axes[1].set_ylim(-xe,xe);axes[1].legend(ncol=3,loc='upper left',frameon=False)
        ft=np.array([(r['tick']-50000000)/1e8 for r in features])
        for axis,key,color in ((axes[2],'audio',PALETTE['audio']),(axes[3],'accel',PALETTE['accel'])):
            fv=[r[key] if r[key] is not None else np.nan for r in features]
            if label!='live' and key=='audio':fv=[v if ft[i]>=-.4 else np.nan for i,v in enumerate(fv)]
            axis.step(ft,fv,where='post',color=color,linewidth=1)
            axis.axhline(config['thresholds'][key],color='#4f5962',linestyle='--',linewidth=.9,label='设定阈值')
            cross=[r for r in ds if r[key+'_cross']]
            axis.scatter([(r['tick']-50000000)/1e8 for r in cross],[r[key] for r in cross],facecolors='none',edgecolors=color,s=35,zorder=4,label='从下向上越过阈值')
            axis.legend(loc='upper right',frameon=False,ncol=2)
        axes[2].set_ylabel('声音变化量\nPCM计数');axes[3].set_ylabel('振动变化量\n标称mg差值')
        if label!='live':axes[2].text(.01,.94,'初始化前0.1秒特征未绘',transform=axes[2].transAxes,va='top',fontsize=8,color='#4f5962')
        for row in ds:
            if row['joint'] and not row['joint']['dedup']:
                for axis in axes:axis.axvline((row['tick']-50000000)/1e8,color='#64497a',linestyle=':',linewidth=1)
        for axis in axes:
            axis.axvline(0,color='#4f5962',linestyle='--',linewidth=.8);axis.grid(axis='y',alpha=.2);axis.set_xlim(-.5,1)
        axes[-1].set_xlabel('距自动保存参考时刻 / s（紫点线为联合判断成功）' if label=='live' else '距手动保存参考时刻 / s（紫点线为联合判断成功）')
        fig.suptitle({'tap':'第一条留出轻敲（响应较弱，仍保留）','sound':'第一条留出纯声（固定短音）','live':'真实在线敲击（自动保存）'}[label],fontsize=12)
        finish(fig)
        name=label+'_aligned';fig.savefig(report/'figures'/f'{name}.pdf');fig.savefig(report/'figures'/f'{name}.png',dpi=160);plt.close(fig)
        index.append({'figure':name,'collection_run_id':collection.name,'trial_id':trial['trial_id'],'event_id':meta['event_id'],
                      'input_hash':meta['input_hash'],'input_directory':directory.relative_to(ROOT).as_posix(),
                      'script':'host/figures.py','script_sha256':sha256(Path(__file__)),
                      'raw_audio_scale':[-ae,ae],'xyz_demeaned_scale':[-xe,xe],
                      'feature_scale':'independent per channel; numeric threshold shown; SNAP audio first0.1s reset transient not drawn',
                      'feature_source':'board_live_CAL' if label=='live' else 'independent_reset_reference',
                      'live_debug_sha256':sha256(collection/'live.json') if label=='live' else None,
                      'source':'board_live' if label=='live' else 'board_snap'})
    index.sort(key=lambda r:0 if r['source']=='board_live' else 1)
    write_json(report/'generated/figure_index.json',index)
    return index
