"""P03: ExG/Otsu proposals, always requiring human review."""
import math
import cv2
import numpy as np


def propose_refinement(rgb, box, padding=0):
    h,w=rgb.shape[:2]
    x1,y1=max(0,math.floor(box[0])),max(0,math.floor(box[1]))
    x2,y2=min(w,math.ceil(box[2])),min(h,math.ceil(box[3]))
    result=dict(candidate_box=None, reason="Không đủ vùng ảnh để co khung.", mask=None)
    if x2-x1<3 or y2-y1<3:
        return result
    roi=rgb[y1:y2,x1:x2].astype(np.int16)
    exg=2*roi[:,:,1]-roi[:,:,0]-roi[:,:,2]
    if exg.max()-exg.min()<8:
        result["reason"]="Màu trong khung gần đồng nhất; giữ khung gốc."
        return result
    normalized=np.clip((exg+510)/4,0,255).astype(np.uint8)
    _,binary=cv2.threshold(normalized,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    binary[(exg<=0)|(roi[:,:,1]<=roi[:,:,0])|(roi[:,:,1]<=roi[:,:,2])]=0
    binary=cv2.morphologyEx(binary,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    count,labels,stats,centers=cv2.connectedComponentsWithStats(binary,8)
    candidates=[i for i in range(1,count) if stats[i,cv2.CC_STAT_AREA]>=max(4,roi.shape[0]*roi.shape[1]*.002)]
    if not candidates:
        result["reason"]="Không tìm thấy vùng cây xanh rõ trong khung."
        return result

    clump_ids=[i for i in range(1,count) if stats[i,cv2.CC_STAT_AREA]>=12]
    if not clump_ids:
        clump_ids=list(candidates)

    clump_boxes: list[list[float]]=[]
    for cid in clump_ids:
        cx,cy,cw,ch,_=map(int,stats[cid])
        clump_boxes.append([
            float(max(float(box[0]),x1+cx)),
            float(max(float(box[1]),y1+cy)),
            float(min(float(box[2]),x1+cx+cw)),
            float(min(float(box[3]),y1+cy+ch)),
        ])

    if len(clump_boxes)>=2:
        min_x=min(cb[0] for cb in clump_boxes)
        min_y=min(cb[1] for cb in clump_boxes)
        max_x=max(cb[2] for cb in clump_boxes)
        max_y=max(cb[3] for cb in clump_boxes)
        candidate=[
            max(float(box[0]),min_x-padding),
            max(float(box[1]),min_y-padding),
            min(float(box[2]),max_x+padding),
            min(float(box[3]),max_y+padding),
        ]
        mask=np.where(np.isin(labels,clump_ids),255,0).astype(np.uint8)
        area=int(sum(stats[cid,cv2.CC_STAT_AREA] for cid in clump_ids))
        width=max(1,int(max_x-min_x))
        height=max(1,int(max_y-min_y))
    else:
        selected=max(candidates,key=lambda i: stats[i,cv2.CC_STAT_AREA])
        x,y,width,height,area=map(int,stats[selected])
        candidate=[max(float(box[0]),x1+x-padding), max(float(box[1]),y1+y-padding),
                   min(float(box[2]),x1+x+width+padding),min(float(box[3]),y1+y+height+padding)]
        mask=np.where(labels==selected,255,0).astype(np.uint8)

    # Estimate whether box contains a single plant or multiple touching rice/tree crowns via distance transform
    dist=cv2.distanceTransform(binary,cv2.DIST_L2,5)
    max_dist=float(dist.max()) if dist.size else 0.0
    estimated_plant_count=max(1,len(clump_boxes))
    if max_dist>=3.0:
        _,peaks=cv2.threshold(dist,0.52*max_dist,255,cv2.THRESH_BINARY)
        peak_count,_,_,_=cv2.connectedComponentsWithStats(peaks.astype(np.uint8),8)
        estimated_plant_count=max(estimated_plant_count,peak_count-1)
    aspect=max(width/max(1,height),height/max(1,width))
    plant_structure="hedge" if aspect>=2.8 and len(clump_boxes)<=2 else ("cluster" if estimated_plant_count>=2 or len(candidates)>=3 else "individual")
    structure_note=" (Phát hiện cụm ~"+str(estimated_plant_count)+" cây/bụi gần nhau)" if estimated_plant_count>=2 else ""

    result.update(candidate_box=candidate, mask=mask, crop=[x1,y1,x2,y2],
                  reason="Đề nghị theo vùng xanh"+structure_note+". Cần xem ảnh để phân biệt lúa với cỏ.",
                  vegetation_fraction=float(area/(roi.shape[0]*roi.shape[1])), components=len(candidates),
                  estimated_plant_count=int(estimated_plant_count), plant_structure=plant_structure,
                  clump_boxes=clump_boxes)
    return result
