"""
Word files become PDFs (7 Nov 2026). The conversion itself needs LibreOffice,
which the Docker image installs; elsewhere that test is skipped, never faked.
"""
import io
import shutil
import unittest

from django.test import SimpleTestCase

from apps.jobs.services.word_to_pdf import is_word, pdf_name, to_pdf

HAS_LIBREOFFICE = bool(shutil.which('soffice') or shutil.which('libreoffice'))


class RecognisingWordFilesTests(SimpleTestCase):

    def test_by_type(self):
        self.assertTrue(is_word('x', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))
        self.assertTrue(is_word('x', 'application/msword'))

    def test_by_name_when_the_type_says_nothing(self):
        self.assertTrue(is_word('Sharon Project work.docx', 'application/octet-stream'))
        self.assertTrue(is_word('letter.RTF', ''))

    def test_pdfs_and_pictures_are_not_word(self):
        self.assertFalse(is_word('cv.pdf', 'application/pdf'))
        self.assertFalse(is_word('photo.jpg', 'image/jpeg'))

    def test_the_pdf_keeps_the_name(self):
        self.assertEqual(pdf_name('Sharon Project work.docx'), 'Sharon Project work.pdf')


@unittest.skipUnless(HAS_LIBREOFFICE, 'LibreOffice is not installed here')
class ConvertingTests(SimpleTestCase):

    def test_a_document_becomes_a_pdf_with_its_pages(self):
        from pypdf import PdfReader
        rtf = rb'{\rtf1\ansi Hello from Farhat.\par}'
        pdf = to_pdf(rtf, 'hello.rtf')
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual(len(PdfReader(io.BytesIO(pdf)).pages), 1)
