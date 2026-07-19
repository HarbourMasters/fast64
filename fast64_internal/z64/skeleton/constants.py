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
        self.isLink = skeletonName in {"gLinkAdultSkel", "gLinkChildSkel", "gDarkLinkSkel"}
        self.restPoseData = restPoseData


ootSkeletonImportDict = OrderedDict(
    {
        "Adult Link": OOTSkeletonImportInfo(
            "gLinkAdultSkel",
            "object_link_boy",
            "ovl_player_actor",
            0,
            [
                (0.0, 3.637500047683716, 0.0),
                (1.5707963705062866, -0.0, 1.5707963705062866),
                (0.0, -0.0, -3.141592502593994),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 1.5707964897155762),
                (0.0, -0.0, 1.919862151145935),
                (0.0, -0.0, 0.0),
                (-3.141592502593994, -1.570796251296997, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (3.141592502593994, 1.570796251296997, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (1.5707964897155762, -0.0, -3.141592502593994),
                (0.0, -0.0, 0.0),
            ],
        ),
        "Child Link": OOTSkeletonImportInfo(
            "gLinkChildSkel",
            "object_link_child",
            "ovl_player_actor",
            1,
            [
                (0.0, 2.2699999809265137, 0.0),
                (1.5707963705062866, -0.0, 1.5707963705062866),
                (0.0, -0.0, -3.141592502593994),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 1.5707964897155762),
                (0.0, -0.0, 1.919862151145935),
                (0.0, -0.0, 0.0),
                (-3.141592502593994, -1.570796251296997, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (3.141592502593994, 1.570796251296997, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (1.5707964897155762, -0.0, -3.141592502593994),
                (0.0, -0.0, 0.0),
            ],
        ),
        "Dark Link": OOTSkeletonImportInfo(
            "gDarkLinkSkel",
            "object_torch2",
            "ovl_En_Torch2",
            None,
            [
                (0.0, 3.637500047683716, 0.0),
                (1.5707963705062866, -0.0, 1.5707963705062866),
                (0.0, -0.0, -3.141592502593994),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, 1.5707964897155762),
                (0.0, -0.0, 1.919862151145935),
                (0.0, -0.0, 0.0),
                (-3.141592502593994, -1.570796251296997, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (3.141592502593994, 1.570796251296997, 0.0),
                (0.0, -0.0, 0.0),
                (0.0, -0.0, -1.5707964897155762),
                (1.5707964897155762, -0.0, -3.141592502593994),
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
