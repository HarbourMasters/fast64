"""HM64 utility functions extracted from upstream."""


def writeXMLData(data, xmlPath):
    xmlFile = open(xmlPath, "w", newline="\n", encoding="utf-8")
    xmlFile.write(data)
    xmlFile.close()
