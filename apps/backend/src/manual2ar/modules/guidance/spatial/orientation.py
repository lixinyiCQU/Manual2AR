"""Explicit user orientation offsets; they do not alter triangulated coordinates."""
import numpy as np
from manual2ar_perception.spatial import project


from manual2ar_perception.spatial import rotation


def axes(origin,basis,camera,intrinsics,distortion,length=.025):
    points=[origin,*[np.asarray(origin)+basis[:,i]/np.linalg.norm(basis[:,i])*length for i in range(3)]]
    pixels=project(points,camera,intrinsics,distortion)
    return [{'id':name,'a':{'x':float(pixels[0][0]),'y':float(pixels[0][1])},'b':{'x':float(pixels[i+1][0]),'y':float(pixels[i+1][1])}} for i,name in enumerate('XYZ')]
