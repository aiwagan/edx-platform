# -*- coding: utf-8 -*-

import unittest
from fs.memoryfs import MemoryFS

from lxml import etree
from mock import Mock, patch

from xmodule.xml_module import is_pointer_tag
from xmodule.modulestore import Location
from xmodule.modulestore.xml import ImportSystem, XMLModuleStore
from xmodule.modulestore.inheritance import compute_inherited_metadata

from .test_export import DATA_DIR

ORG = 'test_org'
COURSE = 'test_course'


class DummySystem(ImportSystem):

    @patch('xmodule.modulestore.xml.OSFS', lambda dir: MemoryFS())
    def __init__(self, load_error_modules):

        xmlstore = XMLModuleStore("data_dir", course_dirs=[], load_error_modules=load_error_modules)
        course_id = "/".join([ORG, COURSE, 'test_run'])
        course_dir = "test_dir"
        policy = {}
        error_tracker = Mock()
        parent_tracker = Mock()

        super(DummySystem, self).__init__(
            xmlstore,
            course_id,
            course_dir,
            policy,
            error_tracker,
            parent_tracker,
            load_error_modules=load_error_modules,
        )

    def render_template(self, template, context):
            raise Exception("Shouldn't be called")


class ImportTestCase(unittest.TestCase):
    '''Make sure module imports work properly, including for malformed inputs'''
    @staticmethod
    def get_system(load_error_modules=True):
        '''Get a dummy system'''
        return DummySystem(load_error_modules)

    def test_fallback(self):
        '''Check that malformed xml loads as an ErrorDescriptor.'''

        bad_xml = '''<sequential display_name="oops"><video url="hi"></sequential>'''
        system = self.get_system()

        descriptor = system.process_xml(bad_xml)

        self.assertEqual(descriptor.__class__.__name__,
                         'ErrorDescriptor')

    def test_unique_url_names(self):
        '''Check that each error gets its very own url_name'''
        bad_xml = '''<sequential display_name="oops"><video url="hi"></sequential>'''
        bad_xml2 = '''<sequential url_name="oops"><video url="hi"></sequential>'''
        system = self.get_system()

        descriptor1 = system.process_xml(bad_xml)
        descriptor2 = system.process_xml(bad_xml2)

        self.assertNotEqual(descriptor1.location, descriptor2.location)

    def test_reimport(self):
        '''Make sure an already-exported error xml tag loads properly'''

        self.maxDiff = None
        bad_xml = '''<sequential display_name="oops"><video url="hi"></sequential>'''
        system = self.get_system()
        descriptor = system.process_xml(bad_xml)

        resource_fs = None
        tag_xml = descriptor.export_to_xml(resource_fs)
        re_import_descriptor = system.process_xml(tag_xml)

        self.assertEqual(re_import_descriptor.__class__.__name__,
                         'ErrorDescriptor')

        self.assertEqual(descriptor.contents,
                         re_import_descriptor.contents)
        self.assertEqual(descriptor.error_msg,
                         re_import_descriptor.error_msg)

    def test_fixed_xml_tag(self):
        """Make sure a tag that's been fixed exports as the original tag type"""

        # create a error tag with valid xml contents
        root = etree.Element('error')
        good_xml = '''<sequential display_name="fixed"><video url="hi"/></sequential>'''
        root.text = good_xml

        xml_str_in = etree.tostring(root)

        # load it
        system = self.get_system()
        descriptor = system.process_xml(xml_str_in)

        # export it
        resource_fs = None
        xml_str_out = descriptor.export_to_xml(resource_fs)

        # Now make sure the exported xml is a sequential
        xml_out = etree.fromstring(xml_str_out)
        self.assertEqual(xml_out.tag, 'sequential')

    def test_metadata_import_export(self):
        """Two checks:
            - unknown metadata is preserved across import-export
            - inherited metadata doesn't leak to children.
        """
        system = self.get_system()
        v = '1 hour'
        url_name = 'test1'
        start_xml = '''
        <course org="{org}" course="{course}"
                due="{due}" url_name="{url_name}" unicorn="purple">
            <chapter url="hi" url_name="ch" display_name="CH">
                <html url_name="h" display_name="H">Two houses, ...</html>
            </chapter>
        </course>'''.format(due=v, org=ORG, course=COURSE, url_name=url_name)
        descriptor = system.process_xml(start_xml)
        compute_inherited_metadata(descriptor)

        self.assertEqual(descriptor.lms.due, v)

        # Check that the child inherits due correctly
        child = descriptor.get_children()[0]
        self.assertEqual(child.lms.due, v)

        # Now export and check things
        resource_fs = MemoryFS()
        exported_xml = descriptor.export_to_xml(resource_fs)

        # Check that the exported xml is just a pointer
        # Exported exported_xml
        pointer = etree.fromstring(exported_xml)
        self.assertTrue(is_pointer_tag(pointer))
        # but it's a special case course pointer
        self.assertEqual(pointer.attrib['course'], COURSE)
        self.assertEqual(pointer.attrib['org'], ORG)

        # Does the course still have unicorns?
        with resource_fs.open('course/{url_name}.xml'.format(url_name=url_name)) as f:
            course_xml = etree.fromstring(f.read())

        self.assertEqual(course_xml.attrib['unicorn'], 'purple')

        # the course and org tags should be _only_ in the pointer
        self.assertTrue('course' not in course_xml.attrib)
        self.assertTrue('org' not in course_xml.attrib)

        # did we successfully strip the url_name from the definition contents?
        self.assertTrue('url_name' not in course_xml.attrib)

        # Does the chapter tag now have a due attribute?
        # hardcoded path to child
        with resource_fs.open('chapter/ch.xml') as f:
            chapter_xml = etree.fromstring(f.read())
        self.assertEqual(chapter_xml.tag, 'chapter')
        self.assertFalse('due' in chapter_xml.attrib)

    def test_is_pointer_tag(self):
        """
        Check that is_pointer_tag works properly.
        """

        yes = ["""<html url_name="blah"/>""",
               """<html url_name="blah"></html>""",
               """<html url_name="blah">    </html>""",
               """<problem url_name="blah"/>""",
               """<course org="HogwartsX" course="Mathemagics" url_name="3.14159"/>"""]

        no = ["""<html url_name="blah" also="this"/>""",
              """<html url_name="blah">some text</html>""",
               """<problem url_name="blah"><sub>tree</sub></problem>""",
               """<course org="HogwartsX" course="Mathemagics" url_name="3.14159">
                     <chapter>3</chapter>
                  </course>
               """]

        for xml_str in yes:
            # should be True for xml_str
            self.assertTrue(is_pointer_tag(etree.fromstring(xml_str)))

        for xml_str in no:
            # should be False for xml_str
            self.assertFalse(is_pointer_tag(etree.fromstring(xml_str)))

    def test_metadata_inherit(self):
        """Make sure that metadata is inherited properly"""

        # Starting import"
        initial_import = XMLModuleStore(DATA_DIR, course_dirs=['toy'])

        courses = initial_import.get_courses()
        self.assertEquals(len(courses), 1)
        course = courses[0]

        def check_for_key(key, node):
            "recursive check for presence of key"
            # Checking node.location.url()
            self.assertTrue(key in node._model_data)
            for c in node.get_children():
                check_for_key(key, c)

        check_for_key('graceperiod', course)

    def test_policy_loading(self):
        """Make sure that when two courses share content with the same
        org and course names, policy applies to the right one."""

        def get_course(name):
            # Importing name

            modulestore = XMLModuleStore(DATA_DIR, course_dirs=[name])
            courses = modulestore.get_courses()
            self.assertEquals(len(courses), 1)
            return courses[0]

        toy = get_course('toy')
        two_toys = get_course('two_toys')

        self.assertEqual(toy.url_name, "2012_Fall")
        self.assertEqual(two_toys.url_name, "TT_2012_Fall")

        toy_ch = toy.get_children()[0]
        two_toys_ch = two_toys.get_children()[0]

        self.assertEqual(toy_ch.lms.display_name, "Overview")
        self.assertEqual(two_toys_ch.lms.display_name, "Two Toy Overview")

        # Also check that the grading policy loaded
        self.assertEqual(two_toys.grade_cutoffs['C'], 0.5999)

        # Also check that keys from policy are run through the
        # appropriate attribute maps -- 'graded' should be True, not 'true'
        self.assertEqual(toy.lms.graded, True)

    def test_definition_loading(self):
        """When two courses share the same org and course name and
        both have a module with the same url_name, the definitions shouldn't clash.

        TODO (vshnayder): once we have a CMS, this shouldn't
        happen--locations should uniquely name definitions.  But in
        our imperfect XML world, it can (and likely will) happen."""

        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['toy', 'two_toys'])

        toy_id = "edX/toy/2012_Fall"
        two_toy_id = "edX/toy/TT_2012_Fall"

        location = Location(["i4x", "edX", "toy", "video", "Welcome"])
        toy_video = modulestore.get_instance(toy_id, location)
        two_toy_video = modulestore.get_instance(two_toy_id, location)
        self.assertEqual(etree.fromstring(toy_video.data).get('youtube'), "1.0:p2Q6BrNhdh8")
        self.assertEqual(etree.fromstring(two_toy_video.data).get('youtube'), "1.0:p2Q6BrNhdh9")

    def test_colon_in_url_name(self):
        """Ensure that colons in url_names convert to file paths properly"""

        # Starting import
        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['toy'])

        courses = modulestore.get_courses()
        self.assertEquals(len(courses), 1)
        course = courses[0]
        course_id = course.id

        # course errors
        for (msg, err) in modulestore.get_item_errors(course.location):
            print msg
            print err

        chapters = course.get_children()
        self.assertEquals(len(chapters), 2)

        ch2 = chapters[1]
        self.assertEquals(ch2.url_name, "secret:magic")

        also_ch2 = modulestore.get_instance(course_id, ch2.location)
        self.assertEquals(ch2, also_ch2)

        # making sure html loaded
        cloc = course.location
        loc = Location(cloc.tag, cloc.org, cloc.course, 'html', 'secret:toylab')
        html = modulestore.get_instance(course_id, loc)
        self.assertEquals(html.lms.display_name, "Toy lab")

    def test_url_name_mangling(self):
        """
        Make sure that url_names are only mangled once.
        """

        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['toy'])

        course = modulestore.get_courses()[0]
        chapters = course.get_children()
        ch1 = chapters[0]
        sections = ch1.get_children()

        self.assertEqual(len(sections), 4)

        for i in (2, 3):
            video = sections[i]
            # Name should be 'video_{hash}'
            print "video {0} url_name: {1}".format(i, video.url_name)

            self.assertEqual(len(video.url_name), len('video_') + 12)

    def test_poll_xmodule(self):
        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['poll'])

        course = modulestore.get_courses()[0]
        chapters = course.get_children()
        ch1 = chapters[0]
        sections = ch1.get_children()

        self.assertEqual(len(sections), 1)

        location = course.location
        location = Location(location.tag, location.org, location.course,
            'sequential', 'Problem_Demos')
        module = modulestore.get_instance(course.id, location)
        self.assertEqual(len(module.children), 3)

    def test_error_on_import(self):
        '''Check that when load_error_module is false, an exception is raised, rather than returning an ErrorModule'''

        bad_xml = '''<sequential display_name="oops"><video url="hi"></sequential>'''
        system = self.get_system(False)

        self.assertRaises(etree.XMLSyntaxError, system.process_xml, bad_xml)

    def test_selfassessment_import(self):
        '''
        Check to see if definition_from_xml in self_assessment_module.py
        works properly.  Pulls data from the self_assessment directory in the test data directory.
        '''

        modulestore = XMLModuleStore(DATA_DIR, course_dirs=['self_assessment'])

        sa_id = "edX/sa_test/2012_Fall"
        location = Location(["i4x", "edX", "sa_test", "selfassessment", "SampleQuestion"])
        sa_sample = modulestore.get_instance(sa_id, location)
        #10 attempts is hard coded into SampleQuestion, which is the url_name of a selfassessment xml tag
        self.assertEqual(sa_sample.max_attempts, '10')
