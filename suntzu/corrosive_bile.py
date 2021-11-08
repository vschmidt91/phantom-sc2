
from sc2.position import Point2

class CorrosiveBile(object):

    def __init__(self, frame: int, position: Point2):
        self.frame: int = frame
        self.position: Point2 = position
        self.frame_expires: int = frame + 49