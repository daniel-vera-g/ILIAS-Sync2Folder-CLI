from config import Config
from helpers import Helpers
from zeep import Client
from zeep import xsd
from pathlib import Path
from datetime import datetime
import untangle
import os
import time

class IliasHandling:
    wsdl = ''
    loggedIn = False
    config = None
    helpers = None
    client = None

    sessionId = ''
    userId = 0

    courseList = []
    fileList = []

    def __init__(self):
        self.config = Config()
        self.helpers = Helpers()
        self.wsdl = self.config.getWsdlUri()
        self.client = Client(wsdl=self.wsdl)

    def iliasLogin(self, user, password):
        """
        Log in to ILIAS,
        Returns false if not successful
        """
        if self.loggedIn:
            return True
        else:
            if (user != '' and password != ''):
                self.config.setUser(user)

                # connect to ILIAS SOAP
                try:
                    # get session id / log in
                    self.sessionId = self.client.service.loginLDAP(self.config.getClient(), user, password)
                    self.userId = self.client.service.getUserIdBySid(self.sessionId)
                    self.loggedIn = True
                    return True
                except:
                    print('Error while logging in!')
                    self.loggedIn = False
                    return False
            else:
                self.loggedIn = False
                return False

    def iliasLogout(self):
        """
        Log out of ILIAS,
        Returns true if successful
        """
        if self.loggedIn:
            self.loggedIn = False
            return self.client.service.logout(self.sessionId)
        else:
            return False

    def getCourseIds(self):
        """
        Get IDs of the courses the user is in, (re)fills the courseList
        """
        self.courseList.clear()

        if not self.loggedIn:
            return
        
        xmlUserRoles = untangle.parse(self.client.service.getUserRoles(self.sessionId, self.userId))

        # scan for "Title" tags (contain the roles with the course ids), add course ids to list
        for obj in xmlUserRoles.Objects.Object:
            role = obj.Title.cdata

            if (role.startswith('il_crs_member') or role.startswith('il_crs_tutor')):
                tmp = role.split('_')
                
                # filter "FSR" course of FH Bielefeld (temporary solution :/)
                if tmp[3] != '39643':
                    self.courseList.append(CourseInfo(courseId=tmp[3]))

    def getCourseNames(self):
        """
        Collect course names matching the course ids
        """
        for course in self.courseList:
            course.courseName = self.getCourseName(course.courseId)

    def getCourseName(self, ref):
        """
        Retrieve course name from given course id
        """
        xmlCourse = untangle.parse(self.client.service.getObjectByReference(self.sessionId, int(ref), self.userId))
        return xmlCourse.Objects.Object.Title.cdata

    def getCourseFiles(self, ref):
        """
        Get the file information, create directories and download files
        """
        self.fileList.clear()

        # get file tree for course
        xmlFileTree = untangle.parse(self.client.service.getXMLTree(self.sessionId, int(ref), types=xsd.SkipValue, user_id=self.userId))

        for obj in xmlFileTree.Objects.Object:
            if obj['type'] == 'file':
                tmpPath = ''
                tmpPathCrs = ''
                tmpPathDownwards = ''

                currentFile = FileInfo()

                # get file id
                currentFile.fileId = obj.References['ref_id']

                # get file path
                for element in obj.References.Path.Element:
                    elementType = element['type']

                    if elementType == 'crs':
                        tmpPathCrs = element.cdata
                    elif elementType == 'fold':
                        tmpPathDownwards = element.cdata
                        tmpPath = os.path.join(tmpPath, tmpPathDownwards)
                currentFile.filePath = os.path.join(tmpPathCrs, tmpPath)

                

                # get file size and version
                for propElement in obj.Properties.Property:
                    if propElement['name'] == 'fileSize':
                        currentFile.fileSize = propElement.cdata
                    if propElement['name'] == 'fileVersion':
                        currentFile.fileVersion = propElement.cdata

                # get creation date
                currentFile.fileDate = obj.CreateDate.cdata

                # get last modified date
                currentFile.fileLastUpdate = obj.LastUpdate.cdata

                # get title
                currentFile.fileName = obj.Title.cdata
        
                self.fileList.append(currentFile)

                # insert progress update here   !!!

        fileCount = len(self.fileList)
        # start file download
        self.downloadFiles(ref, fileCount)

    def downloadFiles(self, ref, fileCount):
        """
        Download each file from given course
        """

        for file in self.fileList:
            # insert progress update here   !!!

            status = 'Not present'

            file.fileStatus = status
            file.fileIsVisible = False

            # create path directories
            path = file.filePath
            if not self.config.getShowOnly():
                # files should be downloaded, create directories
                path = self.createDirectories(path, ref, False)
            else:
                path = self.createDirectories(path, ref, True)
            file.filePath = path

            # check file status
            if os.path.isfile(os.path.join(file.filePath, file.fileName)):
                status = 'Found on disk'
                file.fileStatus = status

                # check if file has been updated
                if int(file.fileVersion) > 1:
                    localLastModified = time.strftime("%Y-%m-%d %T", time.localtime(os.path.getmtime('config.yaml')))
                    fileLastModifyDate = file.fileLastUpdate

                    delta = datetime.strptime(localLastModified, "%Y-%m-%d %H:%M:%S").timestamp() - datetime.strptime(fileLastModifyDate, "%Y-%m-%d %H:%M:%S").timestamp()

                    if delta < 0:
                        # ilias version newer
                        if self.config.getFileIgnore(file.fileId) or self.config.getOverwriteNone():
                            status = 'Update available'
                        else:
                            status = 'Update available!'
                        file.fileStatus = status
            
            # check file ignore rule
            if self.config.getFileIgnore(file.fileId) == file.fileId or self.config.getOverwriteNone():
                file.fileIgnore = "Ignored"
            else:
                file.fileIgnore = "Not ignored"

            # format size to be human readable
            size = int(file.fileSize)
            if size < 1049000:
                # is smaller than 1 MB
                file.fileSize = str(self.helpers.getSizeInKiB(size)) + " KB"
            else:
                file.fileSize = str(self.helpers.getSizeInMiB(size)) + " MB"

            # insert progress update here   !!!

            newFile = False
            if not self.config.getShowOnly():
                # download file
                if not os.path.isfile(os.path.join(file.filePath, file.fileName)):
                    status = 'Loading...'
                    newFile = True
                    file.fileStatus = status
                    file.fileIsVisible = True

                if self.config.getOverwriteAll() and status.startswith('Update available'):
                    size = file.fileSize

                    # implement download function   !!!

                    file.fileSize = size



    def createDirectories(self, path, ref, buildOnlyPath):
        """
        Build the path to the files and (optionally) create non existing directories
        """
        tmpPath = ''
        configPath = self.config.getPath()

        tmpNames = Path(path).parts
        courseName = tmpNames[0]

        if self.config.getUseOwnStructure():
            structTemplate = self.config.getStructTemplate()

            if self.config.getUseOwnNames():
                ownName = self.config.getCourseName(ref)
                if ownName != '__NO_VAL__' and ownName != '':
                    tmpPath = path.replace(courseName, ownName)
                else:
                    tmpPath = path

                if structTemplate != '__NO_VAL__' and structTemplate != '':
                    structTemplate = self.helpers.replaceTemplatePlaceholder(courseName, structTemplate)
                    path = os.path.join(structTemplate, tmpPath)
            elif not self.config.getUseOwnNames():
                if structTemplate != '__NO_VAL__' and structTemplate != '':
                    structTemplate = self.helpers.replaceTemplatePlaceholder(courseName, structTemplate)
                    tmpPath = path
                    path = os.path.join(structTemplate, tmpPath)
        elif not self.config.getUseOwnStructure():
            if self.config.getUseOwnNames():
                ownName = self.config.getCourseName(ref)
                if ownName != '__NO_VAL__' and ownName != '':
                    path = path.replace(courseName, ownName)
        
        path = os.path.join(configPath, path)

        if not buildOnlyPath:
            if not os.path.isdir(path):
                if configPath == '':
                    # implement error   !!!
                    return ''
                
                try:
                    os.makedirs(path)
                except:
                    # implement "path too long" message !!!
                    pass
        return path


class CourseInfo:
    courseChecked = False
    courseName = ''
    courseOwnName = ''
    courseId = ''

    def __init__(self, courseChecked=False, courseName='', courseOwnName='', courseId=''):
        self.courseChecked = courseChecked
        self.courseName = courseName
        self.courseOwnName = courseOwnName
        self.courseId = courseId

class FileInfo:
    fileStatus = 'Missing'
    fileName = ''
    filePath = ''
    fileDate = ''
    fileSize = ''
    fileId = ''
    fileVersion = ''
    fileLastUpdate = ''
    fileIgnore = ''
    fileIsVisible = True

    def __init__(   self, 
                    fileStatus='', 
                    fileName='', 
                    filePath='', 
                    fileDate='', 
                    fileSize='', 
                    fileId='', 
                    fileVersion='', 
                    fileLastUpdate='', 
                    fileIgnore='', 
                    fileIsVisible=True):
        self.fileStatus = fileStatus
        self.fileName = fileName
        self.filePath = filePath
        self.fileDate = fileDate
        self.fileSize = fileSize
        self.fileId = fileId
        self.fileVersion = fileVersion
        self.fileLastUpdate = fileLastUpdate
        self.fileIgnore = fileIgnore
        self.fileIsVisible = fileIsVisible