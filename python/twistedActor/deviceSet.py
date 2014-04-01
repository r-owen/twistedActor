from __future__ import division, absolute_import

import collections
import itertools
import sys
import traceback

from RO.SeqUtil import isSequence
from RO.StringUtil import quoteStr

from .command import UserCmd
from .device import expandUserCmd
from .linkCommands import LinkCommands

__all__ = ["DeviceSet"]

DefaultTimeLim = 5

class DevCmdInfo(object):
    """Information about a device command

    Intended to be passed to callback functions for DeviceSet commands
    """
    def __init__(self, slot, dev, devCmd, userCmd):
        self.slot = slot
        self.dev = dev
        self.devCmd = devCmd
        self.userCmd = userCmd

    def __str__(self):
        return "%s(slot=%s, devCmd=%s)" % \
            (type(self).__name__, self.slot, self.devCmd)

    def __repr__(self):
        return "%s(slot=%s, dev=%s, devCmd=%r, userCmd=%r)" % \
            (type(self).__name__, self.slot, self.dev, self.devCmd, self.userCmd)

class DeviceSet(object):
    """A collection of related devices (e.g. axes or mirrors), some of which may not exist

    Note that a DeviceSet has a list of slot names that is independent of
    the actual devices. This is because a particular device may not exist
    (but its slot should still have a slot), or multiple devices may exist
    that can be swapped out in one slot. For example: suppose a telescope has
    multiple instrument rotator and one can be in use at a particular time (perhaps none).
    In that case the axis DeviceSet's slot names might be ("az", "alt", "rot"),
    while the rotator device in the set might be None or might have a slot such as "rot1" or "rot2".
    """
    def __init__(self, actor, slotList, devList):
        """Construct a DeviceSet

        @param[in] actor: actor (instance of twistedActor.BaseActor);
            used for writeToUsers in this class, and subclasses may make additonal use of it
        @param[in] slotList: slot of each device slot (even if device does not exist)
        @param[in] devList: sequence of devices;
            each device is either an instances of twistedActor.Device or is None if the device is unavailable

        @raise RuntimeError if:
        - len(devList) != len(slotList)
        - names in slotList are not unique
        """
        if len(slotList) != len(devList):
            raise RuntimeError("devList=%s and slotList=%s are not the same length" % \
                (devList, slotList))
        
        self.actor = actor
        # dict of slot name: index
        self._slotIndexDict = dict((slot, i) for i, slot in enumerate(slotList))
        # ordered dict of slot name: device
        self._slotDevDict = collections.OrderedDict((slot, dev) for slot, dev in itertools.izip(slotList, devList))
        # dict of dev.name: slot name
        self._devNameSlotDict = dict((dev.name, slot) for (slot, dev) in self._slotDevDict.iteritems() if dev)

        if len(self._slotDevDict) < len(slotList):
            raise RuntimeError("Names in slotList=%s are not unique" % (slotList,))

        for dev in self.devList:
            if dev:
                self._addDevCallbacks(dev)

    def checkSlotList(self, slotList):
        """Raise RuntimeError if any slots in slotList do not contain a device
        """
        try:
            emptySlotList = [slot for slot in slotList if not self[slot]]
        except KeyError:
            invalidSlotList = [slot for slot in slotList if not slot in self._slotDevDict]
            raise RuntimeError("One or more slots is unknown: %s" % (", ".join(invalidSlotList),))

        if emptySlotList:
            raise RuntimeError("One or more slots is empty: %s" % (", ".join(emptySlotList),))

    def connect(self, slotList=None, userCmd=None, timeLim=DefaultTimeLim):
        """Connect devices specified by slot name

        @param[in] doConnect: if True, connect the specified devices, else disconnect them
        @param[in] slotList: collection of slot names, or None for all filled slots
        @param[in] userCmd: user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim: time limit for each command (sec); None or 0 for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one

        @raise RuntimeError if:
        - a command is specified for an empty or unknown slot
        - userCmd is already done
        """
        # print "%s.connect(slotList=%s, userCmd=%r, timeLim=%r" % (self, slotList, userCmd, timeLim)
        return self._connectOrDisconnect(doConnect=True, slotList=slotList, userCmd=userCmd, timeLim=timeLim)

    def disconnect(self, slotList=None, userCmd=None, timeLim=DefaultTimeLim):
        """Connect devices specified by slot name

        @param[in] doConnect: if True, connect the specified devices, else disconnect them
        @param[in] slotList: collection of slot names, or None for all filled slots
        @param[in] userCmd: user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim: time limit for each command (sec); None or 0 for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one

        @raise RuntimeError if:
        - a command is specified for an empty or unknown slot
        - userCmd is already done
        """
        # print "%s.disconnect(slotList=%s, userCmd=%r, timeLim=%r" % (self, slotList, userCmd, timeLim)
        return self._connectOrDisconnect(doConnect=False, slotList=slotList, userCmd=userCmd, timeLim=timeLim)

    def expandSlotList(self, slotList):
        """Expand a collection of slot names, changing None to the correct list and checking the list

        @param[in] slotList: collection of slot names, or None for all filled slots

        @raise RuntimeError if slotList contains an unknown or empty slot name
        """
        if slotList is None:
            return self.filledSlotList

        self.checkSlotList(slotList)
        return slotList

    @property
    def devExists(self):
        """Return a list of bools, one per device: True if device exists
        """
        return [dev is not None for dev in self._slotDevDict.itervalues()]

    @property
    def devList(self):
        """Return the list of devices
        """
        return self._slotDevDict.values()

    @property
    def slotList(self):
        """Return the list of slot names
        """
        return self._slotDevDict.keys()

    @property
    def filledSlotList(self):
        """Return the list of names of filled slots
        """
        return [slot for slot, dev in self._slotDevDict.iteritems() if dev]
    
    def slotListFromBoolList(self, boolList):
        """Return a list of slot names given a list of bools
        
        @param[in] boolList: a list of bool values of length len(self);

        @return a list of slot names corresponding to True values in boolList

        @warning there is no checking that the slot is filled.
        """
        if len(boolList) != len(self):
            raise RuntimeError("Expected %s bools but got %s" % (len(self), boolList))
        slotList = self._slotDevDict.keys()
        return [slotList[ind] for ind, boolVal in enumerate(boolList) if boolVal] 

    def getIndex(self, slot):
        """Get the index of the slot

        @raise KeyError if slot does not exist
        """
        return self._slotIndexDict[slot]

    def slotFromDevName(self, devName):
        """Get the slot name from the device name
        """
        return self._devNameSlotDict[devName]

    def slotFromIndex(self, index):
        """Get the slot name from the index
        """
        return self._slotDevDict.keys()[index]

    def replaceDev(self, slot, dev, userCmd=None, timeLim=DefaultTimeLim):
        """Replace or remove one device

        The old device (if it exists) is closed by calling init()

        @param[in] slot: slot slot of device (must match a slot in slotList)
        @param[in] dev: the new device, or None to remove the existing device
        @param[in] userCmd: user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim: time limit for each command (sec); None or 0 for no limit

        @return userCmd: the supplied userCmd or a newly created UserCmd

        @raise RuntimeError if slot is not in slotList
        """
        if slot not in self._slotDevDict:
            raise RuntimeError("Invalid slot %s" % (slot,))
        userCmd = expandUserCmd(userCmd)

        if dev is None:
            oldDev = self._slotDevDict[slot]
            self._slotDevDict[slot] = None
            if oldDev:
                self._removeDevCallbacks(oldDev)
                oldDev.init()
            userCmd.setState(userCmd.Done)
            return userCmd

        def initCallback(initCmd, slot=slot, dev=dev, userCmd=userCmd):
            if initCmd.didFail:
                errMsg = "Failed to initialize new %s device %s: %s" % (slot, dev.name, initCmd.getMsg())
                self.actor.writeToUsers("w", "Text=%s" % (quoteStr(errMsg),))

            oldDev = self._slotDevDict[slot]
            if oldDev:
                self._removeDevCallbacks(oldDev)
                oldDev.init()
            self._slotDevDict[slot] = dev
            self._devNameSlotDict[dev.name] = slot
            self._addDevCallbacks(dev)
            if not userCmd.isDone:
                userCmd.setState(userCmd.Done)

        initCmd = UserCmd(callFunc=initCallback)
        dev.connect(userCmd=initCmd, timeLim=timeLim)
        return userCmd

    def startCmd(self, cmdStrOrList, slotList=None, callFunc=None, userCmd=None, timeLim=DefaultTimeLim):
        """Start a command or list of commands on one or more devices

        The same command or list of commands is sent to each device;
        use startCmdDict to send different commands to different devices.

        @param[in] cmdStrOrList: command to send
        @param[in] slotList: collection of slot names, or None for all filled slots
        @param[in] callFunc: callback function to call when each device command succeeds or fails, or None.
            See the description in startCmdList for details.
        @param[in] userCmd: user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim: time limit for each command (sec); None or 0 for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one

        @raise RuntimeError if:
        - slotList has empty or non-existent slots
        - userCmd is already done
        """
        if slotList is None: # don't call expandSlotList because startCmdDict checks the slot names
            slotList = self.filledSlotList
        cmdDict = collections.OrderedDict((slot, cmdStrOrList) for slot in slotList)
        return self.startCmdDict(cmdDict=cmdDict, callFunc=callFunc, userCmd=userCmd)

    def startCmdDict(self, cmdDict, callFunc=None, userCmd=None, timeLim=DefaultTimeLim):
        """Start a dictionary of commands on one or more devices

        @param[in] cmdDict: a dict of slot: command string or sequence of command strings
            if the slot is empty or unknown then an exception is raised
        @param[in] callFunc: callback function to call when each device command succeeds or fails, or None.
            If supplied, the function receives one positional argument: a DevCmdInfo.
            The function may return a new devCmd, in which case the completion of the full set of commands
            is delayed until the new command is finished; one use case is to initialize an actuator if a move fails.
        @param[in] userCmd: user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim: time limit for each command (sec); None or 0 for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one

        @raise RuntimeError if:
        - a command is specified for an empty or unknown slot
        - userCmd is already done
        """
        rcd = RunCmdDict(devSet=self, cmdDict=cmdDict, callFunc=callFunc, userCmd=userCmd, timeLim=timeLim)
        return rcd.userCmd

    def _addDevCallbacks(self, dev):
        """Add device-specific callbacks

        Called when adding a device
        """
        pass

    def _removeDevCallbacks(self, dev):
        """Remove device-specific callbacks

        Called when removing a device
        """
        pass
    
    def _connectOrDisconnect(self, doConnect, slotList, userCmd, timeLim):
        """Connect or disconnect a set of devices

        @param[in] doConnect: if True connect, else disconnect
        @param[in] slotList: collection of slot names, or None for all filled slots
        @param[in] userCmd: user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim: time limit for each command (sec); None or 0 for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one        
        """
        userCmd = expandUserCmd(userCmd)

        slotList = self.expandSlotList(slotList)
        userCmdList = []
        for slot in slotList:
            dev = self[slot]
            if dev:
                if doConnect:
                    connObj = dev.connect(timeLim=timeLim)
                    userCmdList.append(connObj.userCmd)
                else:
                    disconnObj = dev.disconnect(timeLim=timeLim)
                    userCmdList.append(disconnObj.userCmd)
        LinkCommands(userCmd, userCmdList)
        return userCmd

    def __getitem__(self, slot):
        """Return the device in the specified slot
        """
        return self._slotDevDict[slot]

    def __len__(self):
        """Return number of slots"""
        return len(self._slotDevDict)

    def __repr__(self):
        return type(self).__name__


class RunCmdDict(object):
    """Run a dictionary of commands
    """
    def __init__(self, devSet, callFunc, cmdDict, userCmd, timeLim):
        """Start running a command dict

        @param[in] devSet: device set
        @param[in] cmdDict: a dict of slot name: command string or sequence of command strings
        @param[in] callFunc: callback function to call when each device command succeeds or fails, or None.
            If supplied, the function receives one positional argument: a DevCmdInfo.
            The function may return a new devCmd, in which case the completion of the full set of commands
            is delayed until the new command is finished; one use case is to initialize an actuator if a move fails.
        @param[in] userCmd: user command (twistedActor.UserCmd), or None;
            if supplied, its state is set to Done or Failed when the command is done
        @param[in] timeLim: time limit for each command (sec); None or 0 for no limit

        @return userCmd: the specified userCmd or if that was None, then a new empty one
        """
        devSet.checkSlotList(cmdDict.keys())
        self.userCmd = expandUserCmd(userCmd)
        
        self.devCmdDict = dict()
        self.failSlotSet = set()

        for slot, cmdStrOrList in cmdDict.iteritems():
            dev = devSet[slot]

            def devCmdCallback(devCmd, slot=slot, dev=dev):
                if devCmd.didFail:
                    self.failSlotSet.add(slot)
                
                self.devCmdDict[slot] = devCmd

                if callFunc:
                    try:
                        newDevCmd = callFunc(DevCmdInfo(slot=slot, dev=dev, devCmd=devCmd, userCmd=self.userCmd))
                        if newDevCmd:
                            # the callback function started a new command;
                            # update self.devCmdDict and checkDone when it is done, but do NOT run callFunc again
                            self.devCmdDict[slot] = newDevCmd
                            def newDevCmdCallback(devCmd, slot=slot, dev=dev):
                                self.devCmdDict[slot] = devCmd
                                self.checkDone()

                            newDevCmd.addCallback(newDevCmdCallback)
                            self.devCmdDict[slot] = newDevCmd
                    except Exception:
                        self.failSlotSet.add(slot)
                        textBody = "%s command %r failed" % (slot, devCmd.cmdStr)
                        msgStr = "Text=%s" % (quoteStr(textBody),)
                        devSet.actor.writeToUsers("f", msgStr=msgStr)
                        traceback.print_exc(file=sys.stderr)

                self.checkDone()

            if not isSequence(cmdStrOrList):
                devCmd = dev.startCmd(cmdStrOrList, timeLim=timeLim)
            else:
                devCmd = dev.startCmdList(cmdStrOrList, timeLim=timeLim)
            self.devCmdDict[slot] = devCmd
            devCmd.addCallback(devCmdCallback)

        self.checkDone()

    def checkDone(self, dumArg=None):
        """If all device commands are finished, then set self.userCmd state to Failed or Done as appropriate
        """
        for slot, devCmd in self.devCmdDict.iteritems():
            if not devCmd.isDone:
                return
            if devCmd.didFail:
                self.failSlotSet.add(slot)

        if not self.userCmd.isDone:
            if self.failSlotSet:
                failedAxisStr = ", ".join(slot for slot in self.failSlotSet)
                self.userCmd.setState(self.userCmd.Failed, textMsg="Command failed for %s" % (failedAxisStr,))
            else:
                self.userCmd.setState(self.userCmd.Done)
