"""Local-only audit of a recorded application camera viewport; no inference/upload.

The screen crop is resampled to its calibrated pixel domain. Measurements are
recording-derived diagnostics, never a millimetre accuracy or true camera FPS claim.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import cv2
import numpy as np
from manual2ar_perception.spatial import detect_pose,project


def main():
    p=argparse.ArgumentParser();p.add_argument('video',type=Path);p.add_argument('--camera-profile',type=Path,required=True)
    p.add_argument('--target-profile',type=Path,required=True);p.add_argument('--action',default='holder.slide')
    p.add_argument('--viewport',nargs=4,type=int,required=True,metavar=('X','Y','W','H'));p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    c=json.loads(a.camera_profile.read_text());target=json.loads(a.target_profile.read_text())[a.action]
    matrix,distortion=np.array(c['matrix']),np.array(c['distortion']);x,y,w,h=a.viewport
    cap=cv2.VideoCapture(str(a.video));fps=cap.get(cv2.CAP_PROP_FPS);count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));rows=[];updates=[];last_gray=None
    for index in range(count):
        ok,frame=cap.read()
        if not ok:break
        crop=frame[y:y+h,x:x+w]
        if crop.shape[:2]!=(h,w):raise ValueError('Viewport exceeds recording bounds')
        gray=cv2.resize(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),(240,180))
        difference=float(np.mean(cv2.absdiff(gray,last_gray))) if last_gray is not None else 0
        last_gray=gray
        if difference>.7:updates.append(index/fps)
        if index%6:continue
        image=cv2.resize(crop,(c['width'],c['height']))
        pose,state=detect_pose(image,matrix,distortion);row={'time_s':index/fps,'marker_state':state,'display_difference':difference}
        if pose:
            row['reprojection_px']=pose['reprojection_px'];row['marker_corners']=pose['corners'].tolist()
            try:row['target_pixels']=project(target['points_m'],pose['transform'],matrix,distortion).tolist()
            except ValueError:pass
        rows.append(row)
    cap.release();duration=count/fps
    report={'source_sha256':hashlib.sha256(a.video.read_bytes()).hexdigest(),'duration_s':duration,'recording_fps':fps,
        'viewport':a.viewport,'camera_profile_rms_px':c.get('rms_px'),'calibration_views':c.get('views'),
        'target_segment_length_mm':float(np.linalg.norm(np.array(target['points_m'][1])-target['points_m'][0])*1000),
        'authoring_quality':target.get('quality'),
        'sampled_marker_states':dict(Counter(r['marker_state'] for r in rows)),
        'visible_image_changes_per_second_heuristic':len(updates)/duration,
        'limitations':['Viewport coordinates manually reviewed for this recording.',
          'Recorded image differences depend on motion/compression; they are not hardware camera FPS.',
          'Reprojection errors and authored coordinates are not measured physical target errors.'],
        'samples':rows}
    (a.output/'recording-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    summary={k:v for k,v in report.items() if k!='samples'}
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
