# -*- coding: latin-1 -*-
# Author: Fabrice Cros <fabrice.cros@gmail.com>
# URL: http://code.google.com/p/sickbeard/
#
# This file is part of Sick Beard.
#
# Sick Beard is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Sick Beard is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Sick Beard.  If not, see <http://www.gnu.org/licenses/>.

from bs4 import BeautifulSoup
from sickbeard import classes, show_name_helpers, logger, db
from sickbeard.common import Quality
from sickbeard.exceptions import ex

import generic
import cookielib
import sickbeard
import urllib
import urllib2
import json
from datetime import datetime, timedelta
from multiprocessing import Lock
from urllib2 import URLError

class DownloadedEpisode(object):
    
    oldest = None
    youngest = None
    elementsNumber = 0
    sickbeardNumber = 0
    initialized = False
        
    def __init__(self, date=None, link="", isSickBeard=True):
        #Must not be put in default value of the function otherwise the date is always startup the date of the module
        if date == None:
            date = datetime.now()
        self.date = date
        self.link = link
        self.isSickBeard = isSickBeard      #This fields tell if the element has been downloaded by SickBeard
        self.previous = None
        self.next = None
    
    @staticmethod
    def initListFromDB():
        """
            Load DownloadedEpisodes from DB    
        """
        if not DownloadedEpisode.initialized:
            myDB = db.DBConnection()
            eps = myDB.select("SELECT date,link,is_sickbeard from frenchtorrentdb_history ORDER BY date")
            isFirst = True
            previousElement = None
            for ep in eps:
                currentElement = DownloadedEpisode(datetime.strptime(ep["date"],"%Y-%m-%d %H:%M:%S-%f"), ep["link"], ep["is_sickbeard"])
                if isFirst:
                    isFirst = False
                    DownloadedEpisode.addFirstElement(currentElement, True)
                else:
                    previousElement.addYoungerElement(currentElement, True)
                previousElement = currentElement
            DownloadedEpisode.initialized = True
        
    @staticmethod
    def addFirstElement(new, fromDB=False):
        """
            Add a first element to the list
        """
        DownloadedEpisode.elementsNumber += 1
        DownloadedEpisode.youngest = new
        DownloadedEpisode.oldest = new
        if new.isSickBeard:
            DownloadedEpisode.sickbeardNumber += 1
        #If this is not called at DB loading
        if not fromDB:
            #add it to the DB
            myDB = db.DBConnection()                
            myDB.action("INSERT INTO frenchtorrentdb_history (date, link, is_sickbeard) VALUES(?,?,?)", [new.date.strftime("%Y-%m-%d %H:%M:%S-%f"), new.link, new.isSickBeard])
   
    def addYoungerElement(self, new, fromDB=False):
        """
            Add this element as the next
        """
        DownloadedEpisode.elementsNumber += 1
        if new.isSickBeard:
            DownloadedEpisode.sickbeardNumber += 1
        new.previous = self
        new.next = self.next
        self.next = new
        if DownloadedEpisode.youngest == self:
            DownloadedEpisode.youngest = new
        #If this is not called at DB loading
        if not fromDB:
            #add it to the DB
            myDB = db.DBConnection()
            myDB.action("INSERT INTO frenchtorrentdb_history (date, link, is_sickbeard) VALUES(?,?,?)", [new.date.strftime("%Y-%m-%d %H:%M:%S-%f"), new.link, new.isSickBeard])

    def addOlderElement(self, new, fromDB=False):
        """
            Add this element as the previous
        """
        DownloadedEpisode.elementsNumber += 1
        if new.isSickBeard:
            DownloadedEpisode.sickbeardNumber += 1
        new.next = self
        new.previous = self.previous
        self.previous = new
        if DownloadedEpisode.oldest == self:
            DownloadedEpisode.oldest = new
        #If this is not called at DB loading
        if not fromDB:
            #add it to the DB
            myDB = db.DBConnection()
            myDB.action("INSERT INTO frenchtorrentdb_history (date, link, is_sickbeard) VALUES(?,?,?)", [new.date.strftime("%Y-%m-%d %H:%M:%S-%f"), new.link, new.isSickBeard])
           
                       
    @staticmethod
    def removeOlds(duration):
        """
            Remove all episodes older than the duration given in parameter
            Duration must be of timedelta type 
        """
        myDB = db.DBConnection()
        #While oldest element is not the last and is older than the duration given we remove it
        while DownloadedEpisode.elementsNumber > 1 and DownloadedEpisode.oldest.date + duration < datetime.now():
            myDB.action("DELETE FROM frenchtorrentdb_history WHERE link=? and date=? and is_sickbeard=?", [DownloadedEpisode.oldest.link, DownloadedEpisode.oldest.date.strftime("%Y-%m-%d %H:%M:%S-%f"), DownloadedEpisode.oldest.isSickBeard])
            DownloadedEpisode.oldest = DownloadedEpisode.oldest.next
            #Remove reference of old oldest on new oldest
            DownloadedEpisode.oldest.previous.next = None
            #Remove reference on old oldest
            DownloadedEpisode.oldest.previous = None
            DownloadedEpisode.elementsNumber -=1
            if DownloadedEpisode.oldest.isSickBeard:
                DownloadedEpisode.sickbeardNumber -= 1
        
    @staticmethod   
    def addElementWithLink(new, link):
        """
            Add an element knowing only the link of the element just older than it
        """      
        if DownloadedEpisode.youngest == None:
            new.date = datetime.now()
            DownloadedEpisode.addFirstElement(new)
        else:
            element = DownloadedEpisode.youngest
            while element != None:
                #new element is older
                if element.link == link:
                    new.date = element.date - timedelta(microseconds=1)
                    element.addOlderElement(new)
                    break
                else:
                    element = element.previous
        
    @staticmethod           
    def isInList(link):
        """
            Look if a link is in the list
        """
        element = DownloadedEpisode.oldest
        while element != None and element.link != link:
            element = element.next
        
        
        if element != None:
            return True
        else:
            return False
            

class loginError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)


class FrenchTorrentDBProvider(generic.TorrentProvider):
    
    #This field means that a download is taken into account only for this duration
    LIMIT_DURATION = timedelta(hours=24) 
    REINIT_HISTORY_AFTER = timedelta(days=10) 
    REFRESH_HISTORY_RATE = timedelta(minutes=30) #Avoid to refresh faster than this value
    MAX_LOGIN_TRIES = 2         #Must be at least 2
    DOWNLOAD_LIMIT = 30         #MAX DOWNLOADS PER LIMIT_DURATION
    
    def __init__(self):
        
        generic.TorrentProvider.__init__(self, "FrenchTorrentDB")

        self.supportsBacklog = True
        
        self.cj = cookielib.CookieJar()
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cj))
        
        self.url = "http://www.frenchtorrentdb.com"
            
        self.jsRuntime = None
        self.jsContext = None

        self.lastRefresh = datetime.min
        self.loginLock = Lock()
        self.refreshLock = Lock()
                                
    def isEnabled(self):
        return sickbeard.FRENCHTORRENTDB
    
    def getSearchParams(self, searchString, audio_lang, subcat, french=None):
        """
            Return the search parameters for the given category
        """
        url = "group=series"
        if subcat == "Season":
            url += '&' + urllib.urlencode({'adv_cat[s][7]': 199}) #Value for TV Pack
            if audio_lang == "en" and french==None:
                url += '&' + urllib.urlencode({'name': searchString + ' VOSTFR' }) #VO is usually not available in frenchtorrentdb
            elif audio_lang == "fr" or french:
                url += '&' + urllib.urlencode({'name': searchString + ' FRENCH' })
        else:
            url += '&' + urllib.urlencode({'name': searchString});
            if audio_lang == "en" and french==None:
                url += '&' + urllib.urlencode({'adv_cat[s][3]' : 101, 'adv_cat[s][4]' : 191}) #TV VOSTFR SD and HD
            elif audio_lang == "fr" or french:
                url += '&' + urllib.urlencode({'adv_cat[s][1]' : 95, 'adv_cat[s][2]' : 190}) #TV FR SD and HD
                
        return url

            
    def _get_season_search_strings(self, show, season):
        """
            Return a search string for the given season
        """
        showNam = show_name_helpers.allPossibleShowNames(show)
        showNames = list(set(showNam))
        results = []
        patterns = ["%s S%02d"]
        for showName in showNames:
            #Series
            for pattern in patterns:
                results.append( self.getSearchParams(pattern % ( showName, season), show.audio_lang, "Season"))
            #field season does not work for TV Packs
            #results.append( self.getSearchParams(showName, show.audio_lang, "Season")+ "&season=" + str(season))
            # TODO: Do something for Animes
        return results

    def _get_episode_search_strings(self, ep_obj, french=None):
        """
            Return a search string for the given episode
        """
        showNam = show_name_helpers.allPossibleShowNames(ep_obj.show)
        showNames = list(set(showNam))
        results = []
        patterns = ["%s S%02dE%02d","%s %dx%02d"]
        for showName in showNames:
            for pattern in patterns:
                results.append( self.getSearchParams( pattern % ( showName, ep_obj.scene_season, ep_obj.scene_episode), ep_obj.show.audio_lang, "", french ))
            results.append( self.getSearchParams( showName, ep_obj.show.audio_lang, "", french )+ "&season=" + str(ep_obj.scene_season) + "&episode=" + str(ep_obj.scene_episode))
            # TODO: Do something for Animes
        return results
    
    def _get_title_and_url(self, item):
        return (item.title, item.url)
    
    def getQuality(self, item):
        return item.getQuality()
    
    def _doLogin(self, login, password):
        """
            Log into FrenchTorrentDB web site
        """
        try:
            import spidermonkey
        except Exception, e:
            logger.log(u"Impossible to load Python-Spidermonkey module: "+ex(e), logger.ERROR)
            logger.log(u"Python-Spidermonkey must be installed to be able to use FrenchTorrentDB provider. You can follow the instructions from the file 'python-spidermonkey_install.txt' in SickBeard folder", logger.ERROR);
            return False

        try:
            r = self.opener.open( self.url + "/?section=LOGIN&challenge=1" )
        except Exception, e:
            #Exception while loading the page
            logger.log(u"Impossible to reach FrenchTorrentDB website: "+ex(e), logger.WARNING)
            return False
        
        returnToParse = r.read()
        
        try:
            if self.jsRuntime == None:
                self.jsRuntime = spidermonkey.Runtime()
                self.jsContext = self.jsRuntime.new_context()
            #self.jsContext.execute('eval(function(b,c,a,e,d){for(d=function(a){return(a<c?"":d(a/c))+String.fromCharCode(a%c+161)};a--;)e[a]&&(b=b.replace(RegExp(d(a),"g"),e[a]));return b}("\u00a1 a=\'\u00a2\';",2,2,["var","05f"]));')
            #print "a: "+ self.jsContext.execute("a")
            self.jsContext.execute("var a = '05f';")
            self.jsContext.execute("data = "+returnToParse+";")
            self.jsContext.execute("challenge = data.challenge;")
            hashVal = self.jsContext.execute("data.hash")
            self.jsContext.execute("function e(challenge){var s='',i;for(i in challenge){s+=''+eval(challenge[i])}return s}")
            secureLogin = ""+self.jsContext.execute("e(challenge);")
        
            data = urllib.urlencode({'username': login, 'password' : password, 'secure_login' : secureLogin, 'hash' : hashVal, 'code' : 'undefined', 'submit' : 'Connexion'})
            r = self.opener.open(self.url + '/?section=LOGIN&ajax=1', data)
            returnToParse = r.read()
            #This error message happens if we try to connect several times
            #Even if it says that we are not connected, in fact we are
            if returnToParse.decode("iso-8859-1") == u"Vous êtes actuellement déconnecté.":
                return True
            else:
                returnJson = json.loads(returnToParse)
                

            if returnJson["success"] == True:
                return True
            else:
                logger.log(u"FrenchtorrentDB login failed", logger.ERROR)
                logger.log(returnToParse, logger.DEBUG)
                return False
        
            
        except Exception, e:
            logger.log(u"Exception raised in frenchtorrentdb login "+ex(e), logger.WARNING)
            return False
                
    def _refreshHistory(self):
        """
            Look into FrenchTorrentDB history and see if new episodes have been dowloaded outside of SickBeard
        """
        DownloadedEpisode.initListFromDB()
                
        links = []
        page = 1
        while links.__len__() < FrenchTorrentDBProvider.DOWNLOAD_LIMIT:
            #Open the next history page
            r,soup = self._urlOpen(self.url + "?section=TORRENTS&grid_id=&tab=3&menu=2&page="+str(page)+"&navname=#nav_")
            if not soup:
                return False
                
            hisotryTable = soup.find("div", { "class" : "DataGrid" })
    
            if hisotryTable:
                rows = hisotryTable.findAll("ul")
                # TODO: Do something if first history page is empty
                for row in rows:
                    downloadlink = row.find("li", { "class" : "torrents_download" }).find("a")['href'][1:]
                    links.append(self.url + downloadlink)
            else:
                logger.log(u"Unable to parse FrenchTorrentDB history", logger.WARNING)
                logger.log(u"url: "+self.url+"?section=TORRENTS&grid_id=&tab=3&menu=2&page="+str(page)+"&navname=#nav_", logger.DEBUG)
                logger.log(u""+soup.get_text(), logger.DEBUG)
                return False
            page += 1
        
        #If the list is empty
        if DownloadedEpisode.youngest == None:
            #Put only the first link in history in the list
            DownloadedEpisode.addFirstElement(DownloadedEpisode(link=links[0], isSickBeard=False))
            return True
        else:
            youngestPosition = 0
            oldestPosition = 0
            youngestFound = False
            oldestFound = False
            #Try to find the list in history
            for link in links:
                if not youngestFound:
                    if link == DownloadedEpisode.youngest.link:
                        youngestFound = True
                        youngestPosition = oldestPosition
                elif not DownloadedEpisode.isInList(link):
                    #Add the element that we missed to the list
                    DownloadedEpisode.addElementWithLink(DownloadedEpisode(link=link, isSickBeard=False), links[oldestPosition-1])
                    
                if link == DownloadedEpisode.oldest.link:
                    oldestFound = True
                    break
                else:
                    oldestPosition += 1                    

            #if we did not find the youngest episode in the list maybe we have been off for a long time
            #In this case we don't want to wait another 24h but rather consider that we have to reinit the history
            if not youngestFound and DownloadedEpisode.youngest.date + FrenchTorrentDBProvider.REINIT_HISTORY_AFTER < datetime.now():
                DownloadedEpisode.youngest.addYoungerElement(DownloadedEpisode(link=links[0], isSickBeard=False))
            elif youngestPosition != 0:
                #Add all missed links to the list
                for i in xrange(youngestPosition-1, -1, -1):
                    DownloadedEpisode.youngest.addYoungerElement(DownloadedEpisode(link=links[i], isSickBeard=False))
                
        DownloadedEpisode.removeOlds(FrenchTorrentDBProvider.LIMIT_DURATION)
        return True
            
        
    def _isDownloadAllowed(self):
        """
            Check if the limit of downloads has been reached
        """
        refreshTried = False
        #Avoid several refreshes at the same time
        self.refreshLock.acquire()
        #only do the refresh if we are above the limit (Avoids several refresh in seconds)
        if (DownloadedEpisode.youngest == None 
            or self.lastRefresh+FrenchTorrentDBProvider.REFRESH_HISTORY_RATE < datetime.now()):
            self.lastRefresh = datetime.now()
            refreshed = self._refreshHistory()
            refreshTried = True
        self.refreshLock.release()
   
        if ((sickbeard.FRENCHTORRENTDB_USER_LIMIT !=0
            and DownloadedEpisode.sickbeardNumber >= sickbeard.FRENCHTORRENTDB_USER_LIMIT)
            or DownloadedEpisode.elementsNumber >= FrenchTorrentDBProvider.DOWNLOAD_LIMIT):
            #Only print this info once by refresh
            if refreshTried == True:
                logger.log(u"Download limit reached for FrenchTorrentDB")
            return False

        if refreshTried == True and refreshed == False:
            logger.log(u"FrenchTorrentDB history refresh failed. We will naively try to search/download anyway", logger.WARNING)
        
        return True

    def _fillHistoryUntilLimit(self):
        """
            Fill the history with dummy links until limit is reached
        """
        
        self.refreshLock.acquire()
        if (DownloadedEpisode.youngest == None 
            or self.lastRefresh+FrenchTorrentDBProvider.REFRESH_HISTORY_RATE < datetime.now()):
            self._refreshHistory()
            self.lastRefresh = datetime.now()
            
        for i in xrange(0, FrenchTorrentDBProvider.DOWNLOAD_LIMIT - DownloadedEpisode.elementsNumber):
            DownloadedEpisode.youngest.addYoungerElement(DownloadedEpisode(link="dummylink"+datetime.now().strftime("%Y-%m-%d %H:%M:%S-%f"), isSickBeard=False))
        
        self.refreshLock.release()
        
    def _urlOpen(self, url):
        """
            Open the url given and return the response and an HTML soup if its HTML or just what has been read.
            If the page is redirected to the login page then log in is done and the given url is reloaded
        """
        self.loginLock.acquire()
        for i in xrange(FrenchTorrentDBProvider.MAX_LOGIN_TRIES):
            try:
                r = self.opener.open(url)
            except URLError, e:
                #Exception while loading the page
                logger.log(u"Impossible to load FrenchTorrentDB page (" + url + "): "+ex(e), logger.ERROR)
                self.loginLock.release()
                return [None,None]
    
            #if it is HTML content then it might be a login page
            if r.headers.type == "text/html":        
                soup = BeautifulSoup( r )
                isLoginPage = soup.find("form", { "class" : "accountLogin" })
                #If it is a login page, log in
                if isLoginPage:
                    self._doLogin(sickbeard.FRENCHTORRENTDB_USERNAME, sickbeard.FRENCHTORRENTDB_PASSWORD)
                #Otherwise just return it
                else:
                    self.loginLock.release()
                    return [r,soup]
            #Otherwise just return it
            else:
                self.loginLock.release()
                return [r,r.read()]
        #If we reach that point it means that login as failed too many times
        self.loginLock.release()
        raise loginError("Impossible to log into FrenchTorrentDB website")

    
    def _doSearch(self, searchString, show=None, season=None, french=None):
        """
            Use the given URL to search the episodes required
        """
        searchUrl = self.url + '?section=TORRENTS&exact=1&search=Rechercher&' + searchString
        logger.log(u"Search URL: " + searchUrl, logger.DEBUG)     
        
        #Check if we can do the search
        if not self._isDownloadAllowed():
            return []

        results = []
                
        r,soup = self._urlOpen(searchUrl)
        if not soup:
            return []

        resultsTable = soup.find("div", { "class" : "DataGrid" })

        if resultsTable:
            rows = resultsTable.findAll("ul")
    
            for row in rows:
                link = row.find("li", { "class" : "torrents_name" }).find("a", title=True)
                title = link['title']
                downloadlink = row.find("li", { "class" : "torrents_download" }).find("a")['href'][1:]
                downloadURL = (self.url + downloadlink)

                #print downloadURL
                logger.log(u"Download URL: " + downloadURL, logger.DEBUG)
                                
                quality = Quality.nameQuality( title )
                if quality==Quality.UNKNOWN and title:
                    if '720p' not in title.lower() and '1080p' not in title.lower():
                        quality=Quality.SDTV
                if show and french==None:
                    results.append( FrenchTorrentDBSearchResult( link['title'], downloadURL, quality, str(show.audio_lang) ) )
                elif show and french:
                    results.append( FrenchTorrentDBSearchResult( link['title'], downloadURL, quality, 'fr' ) )
                else:
                    results.append( FrenchTorrentDBSearchResult( link['title'], downloadURL, quality ) )
                
        return results
    
    def getResult(self, episodes):
        """
        Returns a result of the correct type for this provider
        """
        result = classes.TorrentDataSearchResult(episodes)
        result.provider = self

        return result    
    
    def getURL(self, url, headers=None):
        """
        Return the Torrent file corresponding to the URL
        """
        downloadFailed = False
               
        if not self._isDownloadAllowed():
            downloadFailed = True
        #Try to download the torrent file
        else:
            try:
                r,torrent = self._urlOpen(url)
                if not r or not torrent:
                    return 
                
                #If it is a torrent file
                if r.headers.type == "application/x-bittorrent":
                    self.refreshLock.acquire()
                    if DownloadedEpisode.youngest == None:
                        DownloadedEpisode.addFirstElement(DownloadedEpisode(link=url, isSickBeard=True))
                    else:
                        DownloadedEpisode.youngest.addYoungerElement(DownloadedEpisode(link=url, isSickBeard=True))
                    self.refreshLock.release()
                    return torrent
                #If limit as been reached return nothing and remove the link from episode_links table
                elif r.headers.type == "text/html":
                    #remove the link from link table so we can download it again later
                    downloadFailed = True
                    logger.log(u"Download limit reached unexpectedly for FrenchTorrentDB. Maybe it's been a long time since you used FrenchTorrentDB. Or you purged the history on the website?", logger.WARNING)
                    self._fillHistoryUntilLimit()
                else:
                    logger.log(u"Unknown type of data. Please report this",logger.ERROR)
                    logger.log(u"URL: "+r.geturl(), logger.DEBUG)
                    logger.log(torrent.get_text(), logger.DEBUG)
                    #Do not delete the link from db  if it fails here
                    return

            except loginError, e:
                #Failed login does not mean that link is broken
                downloadFailed = True
                logger.log(ex(e), logger.WARNING)
            except Exception, e:
                logger.log(u"Impossible to download torrent from FrenchTorrentDB: "+ex(e), logger.ERROR)
                return 

        if downloadFailed == True:
            myDB = db.DBConnection()
            myDB.action("DELETE FROM episode_links where link=?", [url])            
            return
    
class FrenchTorrentDBSearchResult:
    
    def __init__(self, title, url, quality, audio_langs=None):
        self.title = title
        self.url = url
        self.quality = quality
        self.audio_langs=audio_langs
        
    def getQuality(self):
        return self.quality

provider = FrenchTorrentDBProvider()
