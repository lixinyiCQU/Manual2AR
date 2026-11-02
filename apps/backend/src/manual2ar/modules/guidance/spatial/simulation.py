"""Deterministic, labelled synthetic replay. Never a physical printer profile."""
import cv2
import numpy as np
from manual2ar_perception.spatial import marker_corners, project
from .printing import marker_image,MARKER_ID,MARKER_LENGTH


def calibration():
    return {'width':960,'height':720,'matrix':[[850.,0,480],[0,850.,360],[0,0,1]],'distortion':[0.,0,0,0,0],
            'schema_version':'manual2ar-camera-calibration-v1','synthetic':True}


def targets(actions):
    result={key:{'points_m':[[.09,.03,.025],[.09,-.045,.025]],'marker_id':MARKER_ID,
                 'marker_length_m':MARKER_LENGTH,'synthetic':True} for key in actions}
    for key,action in actions.items():
        for index,instance in enumerate(action['target_instances'][1:],1):
            result[key+'::'+instance['id']]={'points_m':[[.09+index*.018,.04,.025],[.09+index*.018,-.02,.025]],
                'marker_id':MARKER_ID,'marker_length_m':MARKER_LENGTH,'synthetic':True}
    return result


def pose(index):
    angle=index/35
    rotation=cv2.Rodrigues(np.array([.17*np.sin(angle),.24*np.cos(angle),.04*np.sin(angle)]))[0]@np.diag([1.,-1,-1])
    transform=np.eye(4);transform[:3,:3]=rotation
    transform[:3,3]=[.045*np.sin(angle),.018*np.cos(angle),.48+.025*np.sin(angle*.7)]
    return transform


def jpeg(index):
    c=calibration();matrix=np.array(c['matrix']);distortion=np.array(c['distortion']);transform=pose(index)
    image=np.full((720,960,3),(30,45,52),np.uint8)
    polygon=project([[-.16,.12,0],[.18,.12,0],[.18,-.14,0],[-.16,-.14,0]],transform,matrix,distortion).astype(np.int32)
    cv2.fillConvexPoly(image,polygon,(80,94,100));cv2.polylines(image,[polygon],True,(180,192,196),2)
    corners=project(marker_corners(MARKER_LENGTH),transform,matrix,distortion).astype(np.float32)
    quiet=project(marker_corners(MARKER_LENGTH*1.2),transform,matrix,distortion).astype(np.int32)
    cv2.fillConvexPoly(image,quiet,(255,255,255))
    homography=cv2.getPerspectiveTransform(np.array([[0,0],[599,0],[599,599],[0,599]],np.float32),corners)
    warped=cv2.warpPerspective(marker_image(),homography,(960,720),flags=cv2.INTER_NEAREST,borderValue=255)
    mask=np.zeros((720,960),np.uint8);cv2.fillConvexPoly(mask,corners.astype(np.int32),255)
    image[mask>0]=cv2.cvtColor(warped,cv2.COLOR_GRAY2BGR)[mask>0]
    target=project([[.07,.05,.025],[.11,.05,.025],[.11,-.06,.025],[.07,-.06,.025]],transform,matrix,distortion).astype(np.int32)
    cv2.fillConvexPoly(image,target,(120,150,160));cv2.polylines(image,[target],True,(210,240,240),2)
    cv2.putText(image,'SYNTHETIC REPLAY - NOT A PRINTER CHECK',(25,45),cv2.FONT_HERSHEY_SIMPLEX,.65,(220,240,240),1,cv2.LINE_AA)
    return cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,92])[1].tobytes()
