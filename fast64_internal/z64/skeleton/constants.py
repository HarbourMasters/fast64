from collections import OrderedDict


# Adding new rest pose entry:
# 1. Import a generic skeleton
# 2. Pose into a usable rest pose
# 3. Select skeleton, then run bpy.ops.object.oot_save_rest_pose()
# 4. Copy array data from console into an OOTSkeletonImportInfo object
#       - list of tuples, first is root position, rest are euler XYZ rotations
# 5. Add object to ootSkeletonImportDict


# Link overlay will be "", since Link texture array data is handled as a special case.
class OOTSkeletonImportInfo:
    def __init__(
        self,
        skeletonName: str,
        folderName: str,
        actorOverlayName: str,
        flipbookArrayIndex2D: int | None,
        restPoseData: list[tuple[float, float, float]] | None,
    ):
        self.skeletonName = skeletonName
        self.folderName = folderName
        self.actorOverlayName = actorOverlayName  # Note that overlayName = None will disable texture array reading.
        self.flipbookArrayIndex2D = flipbookArrayIndex2D
        self.isLink = skeletonName == "gLinkAdultSkel" or skeletonName == "gLinkChildSkel"
        self.restPoseData = restPoseData


ootSkeletonImportDict = OrderedDict(
    {
        "Adult Link": OOTSkeletonImportInfo(
            "gLinkAdultSkel",
            "object_link_boy",
            "",
            0,
            [
                (0.0, 3.640000104904175, 2.7481240749693825e-07),
                (1.5707961320877075, -8.940698137394065e-08, 1.570796251296997),
                (-4.1971347286562377e-07, -1.8346259299077683e-14, 3.141592502593994),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (-2.3369990742594382e-07, 2.3369993584765325e-07, -1.5707964897155762),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (-2.3369990742594382e-07, 2.3369993584765325e-07, -1.5707964897155762),
                (0.0, -0.0, 0.0),
                (-2.104168714822663e-07, -2.104168714822663e-07, 1.5707964897155762),
                (-4.208336576994043e-07, -5.684341886080802e-14, 3.141592502593994),
                (0.0, -0.0, 0.0),
                (3.141592502593994, -1.570796012878418, 0.0),
                (0.0, -0.0, 0.0),
                (-4.0376201582148497e-07, 1.4347639520906341e-08, -1.5707964897155762),
                (-3.141592502593994, 1.570796012878418, 0.0),
                (0.0, -0.0, 0.0),
                (2.2407098754229082e-07, 1.6534342250906775e-07, -1.5707964897155762),
                (1.570796012878418, -8.742278367890322e-08, 3.141592502593994),
                (0.0, -0.0, 0.0),
            ],
        ),
        "Child Link": OOTSkeletonImportInfo(
            "gLinkChildSkel",
            "object_link_child",
            "",
            1,
            [
                (0.0, 2.2799999713897705, 1.7213523051395896e-07),
                (1.570796251296997, -7.16093850883226e-15, 1.570796251296997),
                (-4.197135012873332e-07, -1.8346260993143577e-14, 3.141592502593994),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (-1.8402936063921516e-07, 1.840294032717793e-07, -1.5707964897155762),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (-1.8402936063921516e-07, 1.840294032717793e-07, -1.5707964897155762),
                (0.0, -0.0, 0.0),
                (-2.11797015481352e-07, -2.11797015481352e-07, 1.5707964897155762),
                (-4.1772923964344955e-07, -2.842170943040401e-14, 3.141592502593994),
                (0.0, -0.0, 0.0),
                (3.141592264175415, -1.5707957744598389, 0.0),
                (0.0, -0.0, 0.0),
                (-9.00467512110481e-07, -2.0420276314325747e-07, -1.5707964897155762),
                (3.141592264175415, 1.5707957744598389, 0.0),
                (0.0, -0.0, 0.0),
                (2.0420274893240276e-07, 9.004673415802245e-07, -1.5707964897155762),
                (1.570796012878418, 1.5099581673894136e-07, -3.141592502593994),
                (0.0, -0.0, 0.0),
            ],
        ),
        # "Gerudo": OOTSkeletonImportInfo("gGerudoRedSkel", "object_geldb", "ovl_En_GeldB", None, None),
    }
)

ootEnumSkeletonImportMode = [
    ("Generic", "Generic", "Generic"),
]

for name, info in ootSkeletonImportDict.items():
    ootEnumSkeletonImportMode.append((name, name, name))
