# -*- coding: iso-8859-1 -*-
# Copyright (C) 2000-2010 Bastian Kleineidam
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""
Handle local file: links.
"""

import re
import os
import urlparse
import urllib
import urllib2

from . import urlbase, get_index_html, absolute_url, get_url_from
from .. import log, LOG_CHECK, fileutil, strformat, url as urlutil, firefox
from .const import WARN_FILE_MISSING_SLASH, WARN_FILE_SYSTEM_PATH


def get_files (dirname):
    """Get iterator of entries in directory. Only allows regular files
    and directories, no symlinks."""
    for entry in os.listdir(dirname):
        fullentry = os.path.join(dirname, entry)
        if os.path.islink(fullentry):
            continue
        if os.path.isfile(fullentry):
            yield entry
        elif os.path.isdir(fullentry):
            yield entry+"/"


def prepare_urlpath_for_nt (path):
    """
    URLs like 'file://server/path/' result in a path named '/server/path'.
    However urllib.url2pathname expects '////server/path'.
    """
    if '|' not in path:
        return "////"+path.lstrip("/")
    return path


def get_nt_filename (path):
    """
    Return case sensitive filename for NT path.
    """
    head, tail = os.path.split(path)
    if not tail:
        return path
    for fname in os.listdir(head):
        if fname.lower() == tail.lower():
            return os.path.join(get_nt_filename(head), fname)
    log.error(LOG_CHECK, "could not find %r in %r", tail, head)
    return path


def is_absolute_path (path):
    """Check if given path is absolute. On Windows absolute paths start
    with a drive letter. On all other systems absolute paths start with
    a slash."""
    if os.name == 'nt':
        return re.search(r"^[a-zA-Z]:", path)
    return path.startswith("/")


class FileUrl (urlbase.UrlBase):
    """
    Url link with file scheme.
    """

    def init (self, base_ref, base_url, parent_url, recursion_level,
              aggregate, line, column, name, url_encoding):
        """
        Besides the usual initialization the URL is normed according
        to the platform:
         - the base URL is made an absolute file:// URL
         - under Windows platform the drive specifier is normed
        """
        super(FileUrl, self).init(base_ref, base_url, parent_url,
               recursion_level, aggregate, line, column, name, url_encoding)
        self.scheme = u'file'
        if self.base_url is None:
            return
        base_url = self.base_url
        if not (parent_url or base_ref or base_url.startswith("file:")):
            base_url = os.path.expanduser(base_url)
            if not is_absolute_path(base_url):
                base_url = os.getcwd()+"/"+base_url
                if os.path.isdir(base_url):
                    base_url += "/"
            base_url = "file://"+base_url
        if os.name == "nt":
            base_url = base_url.replace("\\", "/")
            # transform c:/windows into /c|/windows
            base_url = re.sub("^file://(/?)([a-zA-Z]):", r"file:///\2|", base_url)
            # transform file://path into file:///path
            base_url = re.sub("^file://([^/])", r"file:///\1", base_url)
        self.base_url = unicode(base_url)

    def build_url (self):
        """
        Calls super.build_url() and adds a trailing slash to directories.
        """
        super(FileUrl, self).build_url()
        # ignore query and fragment url parts for filesystem urls
        self.urlparts[3] = self.urlparts[4] = ''
        if self.is_directory() and not self.urlparts[2].endswith('/'):
            self.add_warning(_("Added trailing slash to directory."),
                           tag=WARN_FILE_MISSING_SLASH)
            self.urlparts[2] += '/'
        self.url = urlparse.urlunsplit(self.urlparts)

    def add_size_info (self):
        """Get size of file content from filename path."""
        if self.is_directory():
            # Directory size always differs from the customer index.html
            # that is generated. So return without calculating any size.
            return
        self.size = fileutil.get_size(self.get_os_filename())
        if self.dlsize == -1:
            self.dlsize = self.size

    def check_connection (self):
        """
        Try to open the local file. Under NT systems the case sensitivity
        is checked.
        """
        if self.is_directory():
            self.set_result(_("directory"))
        else:
            url = fileutil.pathencode(self.url)
            self.url_connection = urllib2.urlopen(url)
            self.check_case_sensitivity()

    def check_case_sensitivity (self):
        """
        Check if url and windows path name match cases
        else there might be problems when copying such
        files on web servers that are case sensitive.
        """
        if os.name != 'nt':
            return
        path = self.get_os_filename()
        realpath = get_nt_filename(path)
        if path != realpath:
            self.add_warning(_("The URL path %(path)r is not the same as the "
                            "system path %(realpath)r. You should always use "
                            "the system path in URLs.") % \
                            {"path": path, "realpath": realpath},
                               tag=WARN_FILE_SYSTEM_PATH)

    def read_content (self):
        """Return file content, or in case of directories a dummy HTML file
        with links to the files."""
        if self.is_directory():
            data = get_index_html(get_files(self.get_os_filename()))
            if isinstance(data, unicode):
                data = data.encode("iso8859-1", "ignore")
            size = len(data)
        else:
            data, size = super(FileUrl, self).read_content()
        return data, size

    def is_html (self):
        """Check if file is a HTML file."""
        return self.ContentMimetypes.get(self.get_content_type()) == "html"

    def is_css (self):
        """
        Check if file is a CSS file.
        """
        return self.ContentMimetypes.get(self.get_content_type()) == "css"

    def is_file (self):
        """
        This is a file.

        @return: True
        @rtype: bool
        """
        return True

    def get_os_filename (self):
        """
        Construct os specific file path out of the file:// URL.

        @return: file name
        @rtype: string
        """
        path = self.urlparts[2]
        if os.name == 'nt':
            path = prepare_urlpath_for_nt(path)
        return fileutil.pathencode(urllib.url2pathname(path))

    def get_temp_filename (self):
        """Get filename for content to parse."""
        return self.get_os_filename()

    def is_directory (self):
        """
        Check if file is a directory.

        @return: True iff file is a directory
        @rtype: bool
        """
        filename = self.get_os_filename()
        return os.path.isdir(filename) and not os.path.islink(filename)

    def is_parseable (self):
        """
        Check if content is parseable for recursion.

        @return: True if content is parseable
        @rtype: bool
        """
        if self.is_directory():
            return True
        elif firefox.has_sqlite and firefox.extension.search(self.url):
            return True
        else:
            return self.get_content_type() in self.ContentMimetypes

    def parse_url (self):
        """
        Parse file contents for new links to check.
        """
        if self.is_directory():
            self.parse_html()
        elif firefox.has_sqlite and firefox.extension.search(self.url):
            self.parse_firefox()
        else:
            mime = self.get_content_type()
            key = self.ContentMimetypes[mime]
            getattr(self, "parse_"+key)()

    def parse_firefox (self):
        """Parse a Firefox3 bookmark file."""
        log.debug(LOG_CHECK, "Parsing Firefox bookmarks %s", self)
        filename = self.get_os_filename()
        for url, name in firefox.parse_bookmark_file(filename):
            url_data = get_url_from(url, self.recursion_level+1,
                self.aggregate, parent_url=self.url, name=name)
            self.aggregate.urlqueue.put(url_data)

    def get_content_type (self):
        if self.url:
            return fileutil.guess_mimetype(self.url, read=self.get_content)
        return u""

    def get_intern_pattern (self):
        """
        Get pattern for intern URL matching.

        @return non-empty regex pattern or None
        @rtype String or None
        """
        if not self.url:
            return None
        return re.escape(self.url)
