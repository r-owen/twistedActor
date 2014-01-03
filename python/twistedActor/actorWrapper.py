#!/usr/bin/env python
"""Fake Galil actor wrapper.
"""
from .baseWrapper import BaseWrapper

__all__ = ["ActorWrapper"]

class ActorWrapper(BaseWrapper):
    """A wrapper for a twistedActor.Actor talking to one or more wrapped devices
    
    This wrapper is responsible for starting the actor and stopping the devices and actor:
    - It takes a list of wrapped devices that are starting up
    - It builds an Actor when the wrapped devices are ready
    - It stops both on close()
    
    Public attributes include:
    - deviceWrapperList: a list of wrapped devices
    - actor: the actor (None until ready)
    - readyDeferred: called when the actor and fake Galil are ready
      (for tracking closure use the Deferred returned by the close method, or stateCallback).
      
    Subclasses must override _makeActor
    """
    def __init__(self,
        deviceWrapperList,
        userPort = 0,
        stateCallback = None,
    ):
        """Construct a ActorWrapper that manages its devices and controllers

        @param[in] deviceWrapperList: a list of device wrappers (twistedActor.DeviceWrapper);
            each must be starting up or ready
        @param[in] userPort: port for mirror controller connections; 0 to auto-select
        @param[in] stateCallback: function to call when state of actor server socket or any device wrapper changes
            receives one argument: this actor wrapper
        """
        BaseWrapper.__init__(self, stateCallback=stateCallback, callNow=False)
        self.deviceWrapperList = deviceWrapperList
        self._userPort = userPort
        self.actor = None # the actor, once it is built; None until then
        for dw in self.deviceWrapperList:
            dw.addCallback(self._deviceWrapperStateChanged, callNow=False)
        self._deviceWrapperStateChanged()
        
    def _makeActor(self):
        raise NotImplementedError()
    
    @property
    def userPort(self):
        """Return the actor port, if known, else None
        """
        if self.actor:
            return self.actor.server.port
        return None
        
    @property
    def isReady(self):
        """Return True if the actor has connected to the fake hardware controller
        """
        return all(dw.isReady for dw in self.deviceWrapperList) and self.actor and self.actor.server.isReady
    
    @property
    def isDone(self):
        """Return True if the actor and fake hardware controller are fully disconnected
        """
        return all(dw.isDone for dw in self.deviceWrapperList) and self.actor and self.actor.server.isDone
    
    @property
    def didFail(self):
        """Return True if isDone and there was a failure
        """
        return self.isDone and (any(dw.didFail for dw in self.deviceWrapperlist) or self.actor.server.didFail)
    
    def _basicClose(self):
        """Close clients and servers
        """
        if self.actor:
            self.actor.server.close()
        for dw in self.deviceWrapperList:
            dw.close()
    
    def _deviceWrapperStateChanged(self, dumArg=None):
        """Called when the device wrapper changes state
        """
        if not self.actor and all(dw.isReady for dw in self.deviceWrapperList):
            self._makeActor()
            self.actor.server.addStateCallback(self._stateChanged)
        self._stateChanged()