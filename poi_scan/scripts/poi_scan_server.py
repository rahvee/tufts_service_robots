#!/usr/bin/env python
from __future__ import print_function

import rospy
import roslib
roslib.load_manifest('poi_scan')
from std_msgs.msg import String
from std_msgs.msg import Header
import yaml
import rospkg
import os
import actionlib
from move_base_msgs.msg import MoveBaseAction
from move_base_msgs.msg import MoveBaseGoal
from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import Pose
from geometry_msgs.msg import Point
from geometry_msgs.msg import PoseWithCovarianceStamped
from geometry_msgs.msg import Quaternion
from tf.transformations import quaternion_from_euler
import threading
import time
import subprocess
import psutil
import signal
import math

from poi_scan.msg import PoiScanAction, PoiScanGoal


class PoiScanServer:
    def __init__(self):
        #
        self._position_tolerance = 0.5

        self.server = actionlib.SimpleActionServer('poi_scan_server', PoiScanAction, self.execute, False)
        self.server.start()
        rospy.loginfo("ready to perform scanning action")

    def execute(self, goal):
        topics = goal.topics  # type: list
        bagfile_name_prefix = goal.bagfile_name_prefix  # type: str
        num_stops = goal.num_stops  # type: int
        duration = goal.duration  # type: float
        return_to_original = goal.return_to_original  # type: bool

        move_base_client = actionlib.SimpleActionClient('move_base', MoveBaseAction)
        move_base_client.wait_for_server()

        orig_pose = rospy.wait_for_message('/amcl_pose', PoseWithCovarianceStamped).pose.pose  # type: Pose
        move_base_goal = MoveBaseGoal()
        move_base_goal.target_pose.header.frame_id = "/map"
        move_base_goal.target_pose.pose.position = orig_pose.position

        # Always start by facing a consistent direction
        yaw = 0  # radians counter-clockwise relative to map north
        q = quaternion_from_euler(0, 0, yaw)
        move_base_goal.target_pose.pose.orientation = Quaternion(q[0], q[1], q[2], q[3])

        move_base_goal.target_pose.header.stamp = rospy.Time.now()
        move_base_client.send_goal(move_base_goal)
        move_base_client.wait_for_result()

        if not bagfile_name_prefix.startswith("/"):
            # I figure, if they specified an absolute path, they know exactly where the file is going.
            # If they are writing to CWD, it's wherever roscore is running, which is probably not what they expect.
            rospy.logwarn("Warning: bagfiles will be created with prefix {}".format(
                os.path.join(os.getcwd(), bagfile_name_prefix))
            )

        # Explanation of different frames:
        # https://answers.ros.org/question/237295/confused-about-coordinate-frames-can-someone-please-explain/
        # and
        # http://www.ros.org/reps/rep-0105.html
        move_base_goal.target_pose.header.frame_id = "/base_link"
        move_base_goal.target_pose.pose.position = Point(0, 0, 0)  # don't move. Just spin.
        move_base_goal.target_pose.pose.orientation = Point(0, 0, 0)  # don't move. Just spin.
        yaw = 2 * math.pi / num_stops
        q = quaternion_from_euler(0, 0, yaw)
        move_base_goal.target_pose.pose.orientation = Quaternion(q[0], q[1], q[2], q[3])

        for i in range(0, num_stops):
            rospy.loginfo("Position {}/{}".format(i, num_stops - 1))

            # LZ4 is very fast compression, won't slow down your system, usually speeds up your system due to less I/O
            # BZ2 is very compute-intensive, strong, slow compression. Hence not using it here.
            # I found, that if you set_pose 'rosbag' by shelling out like this, you're really just launching another
            # python script that will itself set_pose subprocess. So I'm not changing, but it might be useful to know
            # someday:
            # https://github.com/ros/ros_comm/blob/melodic-devel/tools/rosbag/src/rosbag/rosbag_main.py
            bagfile = bagfile_name_prefix + "_pos{}.bag".format(i)
            cmd = ['rosbag', 'record', '--duration={}'.format(duration), '-O', bagfile, '--lz4']
            cmd.extend(topics)
            rospy.loginfo('Starting rosbag record: {}'.format(cmd))
            bag_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (bag_out, bag_err) = bag_process.communicate()
            rospy.loginfo("stdout from rosbag:")
            rospy.loginfo("{}".format(bag_out))
            rospy.loginfo("stderr from rosbag:")
            rospy.loginfo("{}".format(bag_err))

            move_base_goal.target_pose.header.stamp = rospy.Time.now()
            move_base_client.send_goal(move_base_goal)
            move_base_client.wait_for_result()

        if return_to_original:
            move_base_goal.target_pose.pose.orientation = orig_pose.orientation
            move_base_goal.target_pose.header.stamp = rospy.Time.now()
            move_base_client.send_goal(move_base_goal)
            move_base_client.wait_for_result()
            rospy.loginfo('Returned to original orientation')

        self.server.set_succeeded()


if __name__ == '__main__':
    rospy.init_node('poi_scan_server')
    poi_scan = PoiScanServer()
    rospy.spin()
