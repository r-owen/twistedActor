from __future__ import division, absolute_import
"""For creating twisted log files for use with actors and devices

Logfiles are stored in the directory specified as an argument to startLogging()
Logfiles rollover at noon, and at rollover time the date of the *previous* day is appended to the logfile name.
    A new log is opened and logging continues.
At the time logging is started, a check to the log directory is done. If there is an existing *active*
    logfile (one with no date appended to the file name), logging resumes to that file if the local time is before
    the rollover time for the current log. Else the log is manually rolled over (with the correct date
    appended), and a new twistedActor.log is opened for logging.
"""
import datetime
import logging
import os
import sys
import time
from logging.handlers import TimedRotatingFileHandler
import pyparsing as pp

__all__ = ["parseLogFile", "startLogging", "stopLogging", "writeToLog"]


_NOON = 12*60*60 # in secs
secPerHour = 60*60
noonHour = float(_NOON)/float(secPerHour)


# expose valid logging levels
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL
severity = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

class EmptyFileError(Exception):
    pass

class LogLineParser(object):
    def __init__(self):
        year = pp.Word(pp.nums, exact=4).setResultsName("year").setParseAction(lambda t: int(t[0]))
        month = pp.Word(pp.nums, exact=2).setResultsName("month").setParseAction(lambda t: int(t[0]))
        day = pp.Word(pp.nums, exact=2).setResultsName("day").setParseAction(lambda t: int(t[0]))
        hour = pp.Word(pp.nums, exact=2).setResultsName("hour").setParseAction(lambda t: int(t[0]))
        minute = pp.Word(pp.nums, exact=2).setResultsName("minute").setParseAction(lambda t: int(t[0]))
        second = pp.Word(pp.nums, exact=2).setResultsName("second").setParseAction(lambda t: int(t[0]))
        ms = pp.Word(pp.nums, exact=3).setResultsName("ms").setParseAction(lambda t: int(t[0]))
        dash = pp.Literal("-").suppress()
        colon = pp.Literal(":").suppress()
        period = pp.Literal(".").suppress()
        severity = pp.oneOf("DEBUG INFO WARNING ERROR CRITICAL").suppress()
        msg = pp.restOfLine.setResultsName("msg").setParseAction(lambda t: t[0].strip())
        # alltogether
        self.grammar = year + dash + month + dash + day + hour + colon + minute + colon + second + period + ms + severity + colon + msg

    def __call__(self, line):
        ppOut = self.grammar.parseString(line, parseAll=True)
        datetimeStamp = datetime.datetime(
            ppOut.year,
            ppOut.month,
            ppOut.day,
            ppOut.hour,
            ppOut.minute,
            ppOut.second,
            ppOut.ms * 1000 # milliseconds to microseconds
            )
        return datetimeStamp, ppOut.msg

parseLogLine = LogLineParser()

class NoonRotatingFileHandler(TimedRotatingFileHandler):
    """Modified TimedRotatingFileHandler to rollover at noon.  Note that this is very similar to the
    midnight rollover implementation of the base class.
    """
    def __init__(self, filename, rolloverTime = _NOON):
        self.rolloverTime = rolloverTime
        self._filename = filename
        TimedRotatingFileHandler.__init__(self, filename, when='midnight', interval=1, backupCount=0, encoding=None, delay=False, utc=False)


    def computeRollover(self, currentTime):
            """
            Work out the rollover time based on the specified time.

            Note: this virtually identical to the parent class method (replacing self.rolloverTime vs _MIDNIGHT)
                irrelevant code from parent class method (for other types of rollover) were removed.
            """
            if self.utc:
                t = time.gmtime(currentTime)
            else:
                t = time.localtime(currentTime)
            currentHour = t[3]
            currentMinute = t[4]
            currentSecond = t[5]
            # r is the number of seconds left between now and noon
            r = self.rolloverTime - ((currentHour * 60 + currentMinute) * 60 +
                    currentSecond)
            if r < 0:
                r += 24*60*60
            result = currentTime + r
            return result

def manualRollover(filename, datetime=None, suffix=None):
    """ Rename filename to filename+date

        @param[in] filename: file to be renamed (full path)
        @param[in] datetime: a datetime object from which to extract
            the correct date to be appended
        @param[in] suffix: a string to be appended to the file name

    note: either datetime or suffix must be supplied, but not both
    """
    if datetime and suffix:
        raise RuntimeError("Cannont specify both datetime and suffix")
    if datetime:
        suffix = ".%02d-%02d-%02d" % (datetime.year, datetime.month, datetime.day)
    newfilename = filename + suffix
    n = 1
    while os.path.exists(newfilename): # incase there is already a log file of this name (paranoid?)
        newfilename += ".%i" % n
        n += 1
        if n > 500: # something very wrong
            raise RuntimeError('bug here, infinite loop while searching for available log files names?')
    os.rename(filename, newfilename)

def parseLogFile(logfile):
    # return a list of tuples containing: [(datetime, logMsg)]
    outList = []
    with open(logfile, "r") as f:
        for ind, loggedLine in enumerate(f):
            loggedLine = loggedLine.strip()
            outList.append(parseLogLine(loggedLine))
    return outList

def returnFileHandler(logPath, fName, rolloverTime = _NOON):
    """Get a file handler for logging purposes

    @param[in] logPath: the path to the logging directory

    This function will look in the logPath directory.  If no current log file is present, it will make one.
    If the current log file is old (eg from yesterday), it will rotate it.
    If the current file is todays log file, it will continue to write to that one.
    """
   # fName = 'twistedActor.log'
    filename=os.path.join(logPath, fName)
    if os.path.exists(filename):
        # look at the first line of the current file,
        # decide if we will log to it
        with open(filename, "r") as f:
            firstLine = f.readline()
        try:
            # if firstLine is emtpy don't try and parse it
            # just continue logging to this file
            if not firstLine:
                # file was empty, just log to it
                return NoonRotatingFileHandler(filename, rolloverTime = rolloverTime)
            begLogTime, foo = parseLogLine(firstLine)
        except Exception:
            # logfile in an unexpected format, force a rollover
            manualRollover(filename, suffix="UNRECOGNIZED_BY_LOGGER")
        else:
            # should logging continue to the present log?
            deltaTime = datetime.datetime.now() - begLogTime
            secondsTillRollover = _NOON - ((begLogTime.hour*60 + begLogTime.minute)*60 + begLogTime.second)
            if secondsTillRollover < 0:
                # add 24 hours
                secondsTillRollover += 24*60*60
            if deltaTime.total_seconds() < secondsTillRollover:
                # continue using current log, no rollover
                pass
            elif begLogTime.hour < noonHour:
                # current log should be rolled over with the previous day's
                # date appended (because first entry was before noon)
                manualRollover(filename, begLogTime - datetime.timedelta(days=1))
            else:
                # current log should be rolled over, date suffix should match the
                # first entry of the logfile
                manualRollover(filename, begLogTime)
    fh = NoonRotatingFileHandler(filename, rolloverTime = rolloverTime)
    return fh

class LogStateObj(object):
    def __init__(self):
        self.logger = None # python logging logger
        self.startedLogging = False
        self.fh = None
        self.console = None

LogState = LogStateObj()

def startLogging(logPath, fileName="twistedActor.log", rolloverTime=_NOON, deleteOldLog=False):
    """
        Start logging to a file twistedActor.log.  This file is rotated at noon. After
        rotation a date suffix is added to the file.

        @param[in] logPath: directory where the log file will be placed
        @param[in] fileName: base file name
        @param[in] rolloverTime: time of day (in seconds) at which the log file should rollover
        @param[in] deleteOldLog: if True then any existing log file is deleted; only appropriate for unit tests and fake actors;
            if logging has already started then the existing log file is always retained
     """
    if LogState.startedLogging:
        # logging already started do nothing, add warning to current log
        writeToLog("startLogging called, but logging is already started.", logLevel=WARNING)
        return
    if not os.path.exists(logPath):
        os.makedirs(logPath)
    elif deleteOldLog:
        logFilePath = os.path.join(logPath, fileName)
        if os.path.exists(logFilePath):
            os.remove(logFilePath)
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    fh = returnFileHandler(logPath, fileName, rolloverTime)
    fh.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout) # writes to sys.stderr
    console.setLevel(logging.WARNING)

    logFormatter = logging.Formatter(fmt='%(asctime)s.%(msecs)03d %(levelname)s:  %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    fh.setFormatter(logFormatter)
    consoleFormatter = logging.Formatter("%(levelname)s: %(message)s")
    console.setFormatter(consoleFormatter) # can use a different formatter to not receive time stamp

    logger.addHandler(fh)
    logger.addHandler(console)
    captureStdErr(logger)
    # LogState.logObserver = logObserver
    LogState.logger = logger
    LogState.fh = fh
    LogState.console = console
    LogState.startedLogging = True

def stopLogging():
    if not LogState.startedLogging:
        return # not currently logging, do nothing
    LogState.startedLogging = False
    LogState.logger.removeHandler(LogState.fh)
    LogState.logger.removeHandler(LogState.console)
    LogState.logger = None
    LogState.fh = None
    LogState.console = None


def captureStdErr(logger):
    """Redirect writes to stderr to log, with level ERROR
    """
    sys.stderr = StreamToLogger(logger, log_level=logging.ERROR)

def writeToLog(msgStr, logLevel=logging.INFO):
    """ Write to current log.

        @param[in] msgStr: string to be logged
        @param[in] logLevel: a log level available from pythons logging framework

    If StartedLogging is not set, nothing happens
    Call startLogging to set StartedLogging==True

    """
    if LogState.startedLogging:
        LogState.logger.log(logLevel, msgStr)


## below code is a logging module implementation of twisted's StdioOnnaStick
##
class StreamToLogger(object):
   """
   Fake file-like stream object that redirects writes to a logger instance.

    This code found here:
    http://www.electricmonk.nl/log/2011/08/14/redirect-stdout-and-stderr-to-a-logger-in-python/
   """
   def __init__(self, logger, log_level=logging.INFO):
      self.logger = logger
      self.log_level = log_level
      self.linebuf = ''

   def write(self, buf):
      for line in buf.rstrip().splitlines():
         self.logger.log(self.log_level, line.rstrip())

