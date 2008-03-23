#!/usr/bin/python2.4
#
# Copyright 2007 Google Inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""Unit tests for nss_cache/caches/nssdb.py."""

__author__ = 'jaq@google.com (Jamie Wilkinson)'

import bsddb
import logging
import os.path
import stat
import tempfile
import time
import unittest

from nss_cache import error
from nss_cache import maps
from nss_cache.caches import nssdb

import pmock


class TestNssDbPasswdHandler(pmock.MockTestCase):

  def setUp(self):
    # create a working directory for the test
    self.workdir = tempfile.mkdtemp()

  def tearDown(self):
    # remove the test working directory
    os.rmdir(self.workdir)

  def testConvertValueToMapEntry(self):
    ent = 'foo:x:1000:1001:bar:/:/bin/sh'

    updater = nssdb.NssDbPasswdHandler({})

    pme = updater.ConvertValueToMapEntry(ent)

    self.assertEqual('foo', pme.name)
    self.assertEqual(1000, pme.uid)
    self.assertEqual(1001, pme.gid)
    self.assertEqual('bar', pme.gecos)
    self.assertEqual('/bin/sh', pme.shell)
    self.assertEqual('/', pme.dir)

  def testIsMapPrimaryKey(self):
    updater = nssdb.NssDbPasswdHandler({})

    self.failUnless(updater.IsMapPrimaryKey('.foo'))
    self.failIf(updater.IsMapPrimaryKey('=1000'))
    self.failIf(updater.IsMapPrimaryKey('00'))

  def testNssDbPasswdHandlerWriteData(self):
    entry_string = 'foo:x:1000:1000:foo:/:/bin/sh'

    makedb_stdin = self.mock()
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('.foo %s\n' % entry_string))\
                  .id('write #1')
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('=1000 %s\n' % entry_string))\
                  .id('write #2')\
                  .after('write #1')
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('00 %s\n' % entry_string))\
                  .id('write #3')\
                  .after('write #2')

    passwd_map = maps.PasswdMap()
    passwd_map_entry = maps.PasswdMapEntry()
    passwd_map_entry.name = 'foo'
    passwd_map_entry.uid = 1000
    passwd_map_entry.gid = 1000
    passwd_map_entry.gecos = 'foo'
    passwd_map_entry.dir = '/'
    passwd_map_entry.shell = '/bin/sh'
    passwd_map_entry.passwd = 'x'
    self.failUnless(passwd_map.Add(passwd_map_entry))

    writer = nssdb.NssDbPasswdHandler({'makedb': '/bin/false',
                                       'dir': '/tmp'})

    writer.WriteData(makedb_stdin, passwd_map_entry, 0)

  def testNssDbPasswdHandlerWrite(self):
    ent = 'foo:x:1000:1000:foo:/:/bin/sh'

    makedb_stdin = self.mock()
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('.foo %s\n' % ent))\
                  .id('write #1')
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('=1000 %s\n' % ent))\
                  .id('write #2')\
                  .after('write #1')
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('00 %s\n' % ent))\
                  .id('write #3')\
                  .after('write #2')
    makedb_stdin\
                  .expects(pmock.once())\
                  .method('close')\
                  .after('write #3')

    makedb_stdout = self.mock()
    makedb_stdout\
                   .expects(pmock.once())\
                   .read()\
                   .will(pmock.return_value(''))

    m = maps.PasswdMap()
    pw = maps.PasswdMapEntry()
    pw.name = 'foo'
    pw.uid = 1000
    pw.gid = 1000
    pw.gecos = 'foo'
    pw.dir = '/'
    pw.shell = '/bin/sh'
    pw.passwd = 'x'
    pw.Verify()
    self.failUnless(m.Add(pw))

    class MakeDbDummy(object):
      def wait(self):
        return 0

      def poll(self):
        return None

    def SpawnMakeDb():
      makedb = MakeDbDummy()
      makedb.stdin = makedb_stdin
      makedb.stdout = makedb_stdout
      return makedb

    writer = nssdb.NssDbPasswdHandler({'makedb': '/usr/bin/makedb',
                                       'dir': self.workdir})
    writer._SpawnMakeDb = SpawnMakeDb

    writer.Write(m)

    tmppasswd = os.path.join(self.workdir, 'passwd.db')
    self.failIf(os.path.exists(tmppasswd))
    # just clean it up, Write() doesn't Commit()
    writer._Rollback()

  def testVerify(self):
    # create a map
    m = maps.PasswdMap()
    e = maps.PasswdMapEntry()
    e.name = 'foo'
    e.uid = 1000
    e.gid = 2000
    self.failUnless(m.Add(e))

    updater = nssdb.NssDbPasswdHandler({'dir': self.workdir,
                                        'makedb': '/usr/bin/makedb'})
    updater.Write(m)

    self.failUnless(os.path.exists(updater.cache_filename),
                    'updater.Write() did not create a file')

    retval = updater.Verify(m)

    self.failUnlessEqual(True, retval)

    os.unlink(updater.cache_filename)

  def testVerifyFailure(self):
    # Hide the warning that we expect to get

    class TestFilter(logging.Filter):

      def filter(self, record):
        return not record.msg.startswith('verify failed: %d keys missing')

    fltr = TestFilter()
    logging.getLogger('NssDbPasswdHandler').addFilter(fltr)
    # create a map
    m = maps.PasswdMap()
    e = maps.PasswdMapEntry()
    e.name = 'foo'
    e.uid = 1000
    e.gid = 2000
    self.failUnless(m.Add(e))

    updater = nssdb.NssDbPasswdHandler({'dir': self.workdir,
                                        'makedb': '/usr/bin/makedb'})
    updater.Write(m)

    self.failUnless(os.path.exists(updater.cache_filename),
                    'updater.Write() did not create a file')

    # change the cache
    db = bsddb.btopen(updater.cache_filename)
    del db[db.first()[0]]
    db.sync()
    db.close()

    retval = updater.Verify(m)

    self.failUnlessEqual(False, retval)
    self.failIf(os.path.exists(os.path.join(updater.cache_filename)))
    # no longer hide this message
    logging.getLogger('NssDbPasswdHandler').removeFilter(fltr)

  def testVerifyEmptyMap(self):
    updater = nssdb.NssDbPasswdHandler({'dir': self.workdir})
    map_data = maps.PasswdMap()
    # create a temp file, clag it into the updater object
    (_, temp_filename) = tempfile.mkstemp(prefix='nsscache',
                                          dir=self.workdir)
    updater.cache_filename = temp_filename
    # make it empty
    db = bsddb.btopen(temp_filename, 'w')
    self.assertEqual(0, len(db))
    db.close()
    # TODO(jaq): raising an exception is probably the wrong behaviour
    self.assertRaises(error.EmptyMap, updater.Verify, map_data)
    os.unlink(temp_filename)


class TestNssDbGroupHandler(pmock.MockTestCase):

  def setUp(self):
    # create a working directory for the test
    self.workdir = tempfile.mkdtemp()

  def tearDown(self):
    # remove the test working directory
    os.rmdir(self.workdir)

  def testConvertValueToMapEntry(self):
    ent = 'foo:x:1000:bar'
    updater = nssdb.NssDbGroupHandler({})

    gme = updater.ConvertValueToMapEntry(ent)

    self.assertEqual('foo', gme.name)
    self.assertEqual(1000, gme.gid)
    self.assertEqual('x', gme.passwd)
    self.assertEqual(['bar'], gme.members)

  def testIsMapPrimaryKey(self):
    updater = nssdb.NssDbGroupHandler({})

    self.failUnless(updater.IsMapPrimaryKey('.foo'))
    self.failIf(updater.IsMapPrimaryKey('=1000'))
    self.failIf(updater.IsMapPrimaryKey('00'))

  def testNssDbGroupHandlerWriteData(self):
    ent = 'foo:x:1000:bar'

    makedb_stdin = self.mock()
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('.foo %s\n' % ent))\
                  .id('write #1')
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('=1000 %s\n' % ent))\
                  .id('write #2')\
                  .after('write #1')
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('00 %s\n' % ent))\
                  .id('write #3')\
                  .after('write #2')

    m = maps.GroupMap()
    g = maps.GroupMapEntry()
    g.name = 'foo'
    g.gid = 1000
    g.passwd = 'x'
    g.members = ['bar']

    self.failUnless(m.Add(g))

    writer = nssdb.NssDbGroupHandler({'makedb': '/bin/false',
                                      'dir': '/tmp'})

    writer.WriteData(makedb_stdin, g, 0)

  def testNssDbGroupHandlerWrite(self):
    ent = 'foo:x:1000:bar'

    makedb_stdin = self.mock()
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('.foo %s\n' % ent))\
                  .id('write #1')
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('=1000 %s\n' % ent))\
                  .id('write #2')\
                  .after('write #1')
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('00 %s\n' % ent))\
                  .id('write #3')\
                  .after('write #2')
    makedb_stdin\
                  .expects(pmock.once())\
                  .method('close')\
                  .after('write #3')

    makedb_stdout = self.mock()
    makedb_stdout\
                   .expects(pmock.once())\
                   .read()\
                   .will(pmock.return_value(''))

    m = maps.GroupMap()
    g = maps.GroupMapEntry()
    g.name = 'foo'
    g.gid = 1000
    g.passwd = 'x'
    g.members = ['bar']
    g.Verify()
    self.failUnless(m.Add(g))

    class MakeDbDummy(object):
      def wait(self):
        return 0

      def poll(self):
        return None

    def SpawnMakeDb():
      makedb = MakeDbDummy()
      makedb.stdin = makedb_stdin
      makedb.stdout = makedb_stdout
      return makedb

    writer = nssdb.NssDbGroupHandler({'makedb': '/usr/bin/makedb',
                                      'dir': self.workdir})
    writer._SpawnMakeDb = SpawnMakeDb

    writer.Write(m)

    tmpgroup = os.path.join(self.workdir, 'group.db')
    self.failIf(os.path.exists(tmpgroup))
    # just clean it up, Write() doesn't Commit()
    writer._Rollback()

  def testVerify(self):
    # create a map
    m = maps.GroupMap()
    e = maps.GroupMapEntry()
    e.name = 'foo'
    e.gid = 2000
    self.failUnless(m.Add(e))

    updater = nssdb.NssDbGroupHandler({'dir': self.workdir,
                                       'makedb': '/usr/bin/makedb'})
    updater.Write(m)

    self.failUnless(os.path.exists(updater.cache_filename),
                    'updater.Write() did not create a file')

    retval = updater.Verify(m)

    self.failUnlessEqual(True, retval)
    os.unlink(updater.cache_filename)

  def testVerifyFailure(self):
    # Hide the warning that we expect to get

    class TestFilter(logging.Filter):
      def filter(self, record):
        return not record.msg.startswith('verify failed: %d keys missing')

    fltr = TestFilter()
    logging.getLogger('NssDbGroupHandler').addFilter(fltr)

    # create a map
    m = maps.GroupMap()
    e = maps.GroupMapEntry()
    e.name = 'foo'
    e.gid = 2000
    self.failUnless(m.Add(e))

    updater = nssdb.NssDbGroupHandler({'dir': self.workdir,
                                       'makedb': '/usr/bin/makedb'})
    updater.Write(m)

    self.failUnless(os.path.exists(updater.cache_filename),
                    'updater.Write() did not create a file')

    # change the cache
    db = bsddb.btopen(updater.cache_filename)
    del db[db.first()[0]]
    db.sync()
    db.close()

    retval = updater.Verify(m)

    self.failUnlessEqual(False, retval)
    self.failIf(os.path.exists(os.path.join(updater.cache_filename)))
    # no longer hide this message
    logging.getLogger('NssDbGroupHandler').removeFilter(fltr)


class TestNssDbShadowHandler(pmock.MockTestCase):

  def setUp(self):
    # create a working directory for the test
    self.workdir = tempfile.mkdtemp()

  def tearDown(self):
    # remove the test working directory
    os.rmdir(self.workdir)

  def testConvertValueToMapEntry(self):
    ent = 'foo:*:::::::0'

    updater = nssdb.NssDbShadowHandler({})

    sme = updater.ConvertValueToMapEntry(ent)

    self.assertEqual('foo', sme.name)
    self.assertEqual('*', sme.passwd)
    self.assertEqual(0, sme.flag)

  def testIsMapPrimaryKey(self):
    updater = nssdb.NssDbShadowHandler({})

    self.failUnless(updater.IsMapPrimaryKey('.foo'))
    self.failIf(updater.IsMapPrimaryKey('00'))

  def testNssDbShadowHandlerWriteData(self):
    ent = 'foo:!!:::::::0'

    makedb_stdin = self.mock()
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('.foo %s\n' % ent))\
                  .id('write #1')
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('00 %s\n' % ent))\
                  .id('write #2')\
                  .after('write #1')

    m = maps.ShadowMap()
    s = maps.ShadowMapEntry()
    s.name = 'foo'

    self.failUnless(m.Add(s))

    writer = nssdb.NssDbShadowHandler({'makedb': '/bin/false',
                                       'dir': '/tmp'})

    writer.WriteData(makedb_stdin, s, 0)

  def testNssDbShadowHandlerWrite(self):
    ent = 'foo:*:::::::0'

    makedb_stdin = self.mock()
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('.foo %s\n' % ent))\
                  .id('write #1')
    makedb_stdin\
                  .expects(pmock.once())\
                  .write(pmock.eq('00 %s\n' % ent))\
                  .id('write #2')\
                  .after('write #1')
    makedb_stdin\
                  .expects(pmock.once())\
                  .method('close')\
                  .after('write #2')

    makedb_stdout = self.mock()
    makedb_stdout.expects(pmock.once()).read().will(pmock.return_value(''))

    m = maps.ShadowMap()
    s = maps.ShadowMapEntry()
    s.name = 'foo'
    s.passwd = '*'
    s.Verify()
    self.failUnless(m.Add(s))

    class MakeDbDummy(object):
      def wait(self):
        return 0

      def poll(self):
        return None

    def SpawnMakeDb():
      makedb = MakeDbDummy()
      makedb.stdin = makedb_stdin
      makedb.stdout = makedb_stdout
      return makedb

    writer = nssdb.NssDbShadowHandler({'makedb': '/usr/bin/makedb',
                                       'dir': self.workdir})
    writer._SpawnMakeDb = SpawnMakeDb

    writer.Write(m)

    tmpshadow = os.path.join(self.workdir, 'shadow.db')
    self.failIf(os.path.exists(tmpshadow))
    # just clean it up, Write() doesn't Commit()
    writer._Rollback()

  def testVerify(self):
    m = maps.ShadowMap()
    s = maps.ShadowMapEntry()
    s.name = 'foo'
    self.failUnless(m.Add(s))

    updater = nssdb.NssDbShadowHandler({'dir': self.workdir,
                                        'makedb': '/usr/bin/makedb'})
    updater.Write(m)

    self.failUnless(os.path.exists(updater.cache_filename),
                    'updater.Write() did not create a file')

    retval = updater.Verify(m)

    self.failUnlessEqual(True, retval)
    os.unlink(updater.cache_filename)

  def testVerifyFailure(self):
    # Hide the warning that we expect to get

    class TestFilter(logging.Filter):
      def filter(self, record):
        return not record.msg.startswith('verify failed: %d keys missing')

    fltr = TestFilter()
    logging.getLogger('NssDbShadowHandler').addFilter(fltr)

    # create a map
    m = maps.ShadowMap()
    s = maps.ShadowMapEntry()
    s.name = 'foo'
    self.failUnless(m.Add(s))

    updater = nssdb.NssDbShadowHandler({'dir': self.workdir,
                                        'makedb': '/usr/bin/makedb'})
    updater.Write(m)

    self.failUnless(os.path.exists(updater.cache_filename),
                    'updater.Write() did not create a file')

    # change the cache
    db = bsddb.btopen(updater.cache_filename)
    del db[db.first()[0]]
    db.sync()
    db.close()

    retval = updater.Verify(m)

    self.failUnlessEqual(False, retval)
    self.failIf(os.path.exists(os.path.join(updater.cache_filename)))
    # no longer hide this message
    logging.getLogger('NssDbShadowHandler').removeFilter(fltr)


class TestNssDbCache(unittest.TestCase):

  def setUp(self):
    # create a working directory for the test
    self.workdir = tempfile.mkdtemp()

  def tearDown(self):
    # remove the test working directory
    os.rmdir(self.workdir)

  def testWriteTestBdb(self):
    data = maps.PasswdMap()
    pw = maps.PasswdMapEntry()
    pw.name = 'foo'
    pw.passwd = 'x'
    pw.uid = 1000
    pw.gid = 1000
    pw.gecos = 'poop'
    pw.dir = '/'
    pw.shell = '/bin/sh'
    self.failUnless(data.Add(pw))

    # instantiate object under test
    dummy_config = {'dir': self.workdir}
    cache = nssdb.NssDbPasswdHandler(dummy_config)

    r = cache.Write(data)

    self.assertEqual(True, r)

    # perform test
    db = bsddb.btopen(cache.cache_filename, 'r')

    self.assertEqual(3, len(db.keys()))
    self.failUnless('.foo' in db.keys())
    self.failUnless('=1000' in db.keys())
    self.failUnless('00' in db.keys())

    # convert data to pwent
    d = '%s:x:%s:%s:%s:%s:%s\x00' % (pw.name, pw.uid, pw.gid, pw.gecos,
                                     pw.dir, pw.shell)
    self.assertEqual(db['00'], d)
    self.assertEqual(db['.foo'], d)
    self.assertEqual(db['=1000'], d)

    # tear down
    os.unlink(cache.cache_filename)

  def testLoadBdbCacheFile(self):
    pass_file = os.path.join(self.workdir, 'passwd.db')
    db = bsddb.btopen(pass_file, 'c')
    ent = 'foo:x:1000:500:bar:/:/bin/sh'
    db['00'] = ent
    db['=1000'] = ent
    db['.foo'] = ent
    db.sync()
    self.failUnless(os.path.exists(pass_file))

    config = {'dir': self.workdir}
    cache = nssdb.NssDbPasswdHandler(config)
    data_map = cache.GetMap()
    cache._LoadBdbCacheFile(data_map)
    self.assertEqual(1, len(data_map))

    # convert data to pwent
    x = data_map.PopItem()
    d = '%s:x:%s:%s:%s:%s:%s' % (x.name, x.uid, x.gid, x.gecos, x.dir, x.shell)
    self.assertEqual(ent, d)

    os.unlink(pass_file)

  def testLoadBdbCacheFileRaisesCacheNotFound(self):
    bad_file = os.path.join(self.workdir, 'really_not_going_to_exist_okay')
    self.failIf(os.path.exists(bad_file), 'what the hell, it exists!')

    config = {}
    cache = nssdb.NssDbPasswdHandler(config)
    cache.CACHE_FILENAME = bad_file
    data = cache.GetMap()
    self.assertRaises(error.CacheNotFound, cache._LoadBdbCacheFile, data)

  def testBeginRaisesPermissionDenied(self):
    os.chmod(self.workdir, 0)
    config = {'dir': self.workdir}
    cache = nssdb.NssDbPasswdHandler(config)
    self.assertRaises(error.PermissionDenied, cache._Begin)
    os.chmod(self.workdir, 0700)

  def testGetTimestampNoTimestamp(self):
    cache = nssdb.NssDbCache({'dir': self.workdir})
    cache.CACHE_FILENAME = 'nothing.db'
    timestamp = cache._ReadTimestamp('anything')
    self.assertEqual(None, timestamp)

  def testGetTimestampFileUnreadable(self):
    # hide the warning we expect to get

    class TestFilter(logging.Filter):
      def filter(self, record):
        return not record.msg.startswith('error opening timestamp file')

    flt = TestFilter()
    logging.getLogger('NssDbCache').addFilter(flt)
    cache = nssdb.NssDbCache({'dir': self.workdir})
    cache.CACHE_FILENAME = 'passwd.db'
    ts_filename = os.path.join(self.workdir,
                               'passwd.db.nsscache-timestamp')
    ts_file = open(ts_filename, 'w')
    ts_file.write('\n')
    ts_file.close()
    os.chmod(ts_filename, 0)
    timestamp = cache._ReadTimestamp('nsscache-timestamp')
    self.failUnlessEqual(None, timestamp)
    os.chmod(ts_filename, stat.S_IWUSR)
    os.unlink(ts_filename)
    logging.getLogger('NssDbCache').removeFilter(flt)

  def testGetTimestamp(self):
    # we don't guarantee anything better than second resolution in our
    # timestamps
    now = int(time.time())

    ts_file = open(os.path.join(self.workdir,
                                'nothing.db.nsscache-timestamp'), 'w')
    ts_file.write('%s\n' % time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                         time.gmtime(now)))
    ts_file.close()
    cache = nssdb.NssDbCache({'dir': self.workdir})
    cache.CACHE_FILENAME = 'nothing.db'
    timestamp = cache._ReadTimestamp('nsscache-timestamp')

    self.assertEqual(now, timestamp)
    os.unlink(os.path.join(self.workdir, 'nothing.db.nsscache-timestamp'))

  def testGetTimestampBadFormat(self):
    # hide the warning that we expect to get

    class TestFilter(logging.Filter):
      def filter(self, record):
        return not record.msg.startswith('cannot parse timestamp file')

    flt = TestFilter()
    # attach our filter to the logger attached to our updater
    logging.getLogger('NssDbCache').addFilter(flt)

    now = time.time()
    ts_file = open(os.path.join(self.workdir,
                                'passwd.db.nsscache-timestamp'), 'w')
    ts_file.write('%s\n' % now)
    ts_file.close()
    cache = nssdb.NssDbCache({'dir': self.workdir})
    cache.CACHE_FILENAME = 'passwd.db'
    timestamp = cache._ReadTimestamp('nsscache-timestamp')

    self.assertEqual(None, timestamp)
    os.unlink(os.path.join(self.workdir, 'passwd.db.nsscache-timestamp'))
    # no longer hide this message
    logging.getLogger('NssDbCache').removeFilter(flt)

  def testWriteTimestamp(self):
    cache = nssdb.NssDbCache({'dir': self.workdir})
    cache.CACHE_FILENAME = 'nothing.db'
    self.assertEquals(True,
                      cache._WriteTimestamp(0, 'nsscache-update-timestamp'))
    update_ts_filename = os.path.join(self.workdir,
                                      'nothing.db.nsscache-update-timestamp')
    self.failUnless(os.path.exists(update_ts_filename))
    os.unlink(update_ts_filename)

  def testWriteUpdateTimestamp(self):

    def FakeWriteTimestamp(timestamp, name):
      self.failIfEqual(None, timestamp)
      self.assertEqual('nsscache-update-timestamp', name)
      return True

    cache = nssdb.NssDbCache({'dir': self.workdir})
    cache._WriteTimestamp = FakeWriteTimestamp
    self.assertEquals(True, cache.WriteUpdateTimestamp())

  def testHasLastUpdateTimestamp(self):
    timestamp = int(time.time())
    update_ts_filename = os.path.join(self.workdir,
                                      'nothing.db.nsscache-update-timestamp')
    update_ts_file = open(update_ts_filename, 'w')
    update_ts_file.write('%s\n' % time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                                time.gmtime(timestamp)))
    update_ts_file.close()
    db_filename = os.path.join(self.workdir, 'nothing.db')
    db = bsddb.btopen(db_filename)
    db.close()
    cache = nssdb.NssDbCache({'dir': self.workdir})
    cache.CACHE_FILENAME = 'nothing.db'
    self.assertEquals(timestamp, cache.GetUpdateTimestamp())
    os.unlink(update_ts_filename)
    os.unlink(db_filename)

  def testGetMapIsSizedObject(self):
    timestamp = int(time.time())
    update_ts_filename = os.path.join(self.workdir,
                                      'passwd.db.nsscache-update-timestamp')
    update_ts_file = open(update_ts_filename, 'w')
    update_ts_file.write('%s\n' % time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                                time.gmtime(timestamp)))
    update_ts_file.close()
    db_filename = os.path.join(self.workdir, 'passwd.db')
    db = bsddb.btopen(db_filename)
    db.close()
    cache = nssdb.NssDbPasswdHandler({'dir': self.workdir})
    cache_map = cache.GetCacheMap()
    self.assertEquals(0, len(cache_map))
    os.unlink(update_ts_filename)
    os.unlink(db_filename)

  def testGetCacheMapHasMerge(self):
    timestamp = int(time.time())
    update_ts_filename = os.path.join(self.workdir,
                                      'passwd.db.nsscache-update-timestamp')
    update_ts_file = open(update_ts_filename, 'w')
    update_ts_file.write('%s\n' % time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                                time.gmtime(timestamp)))
    update_ts_file.close()
    db_filename = os.path.join(self.workdir, 'passwd.db')
    db = bsddb.btopen(db_filename)
    db.close()
    cache = nssdb.NssDbPasswdHandler({'dir': self.workdir})
    cache_map = cache.GetCacheMap()
    self.assertEquals(False, cache_map.Merge(maps.PasswdMap()))
    os.unlink(update_ts_filename)
    os.unlink(db_filename)

  def testGetCacheMapIsIterable(self):
    timestamp = int(time.time())
    update_ts_filename = os.path.join(self.workdir,
                                      'passwd.db.nsscache-update-timestamp')
    update_ts_file = open(update_ts_filename, 'w')
    update_ts_file.write('%s\n' % time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                                time.gmtime(timestamp)))
    update_ts_file.close()
    db_filename = os.path.join(self.workdir, 'passwd.db')
    db = bsddb.btopen(db_filename)
    db.close()
    cache = nssdb.NssDbPasswdHandler({'dir': self.workdir})
    cache_map = cache.GetCacheMap()
    self.assertEquals([], list(cache_map))
    os.unlink(update_ts_filename)
    os.unlink(db_filename)


if __name__ == '__main__':
  unittest.main()
