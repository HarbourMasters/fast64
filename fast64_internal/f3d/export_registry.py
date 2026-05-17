"""Export format registry. Extensions register exporters here."""

_xml_exporter = None


def register_xml_exporter(exporter_module):
    global _xml_exporter
    _xml_exporter = exporter_module


def get_xml_exporter():
    return _xml_exporter
