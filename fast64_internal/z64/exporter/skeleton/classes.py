from __future__ import annotations
import mathutils

from dataclasses import dataclass, field, KW_ONLY
from abc import abstractmethod, ABC
from ....f3d.f3d_writer import GfxList
from ....f3d.f3d_gbi import Vtx, FMesh
from ....utility import CData, toAlnum
from ...model_classes import LimbSkinType
from ...model_classes import SkinAnimData


@dataclass
class OOTBaseLimb(ABC):
    skeletonName: str
    boneName: str
    index: int
    translation: mathutils.Vector
    _: KW_ONLY
    typeName: str = ""
    _children: list[OOTBaseLimb] = field(default_factory=list)
    firstChildIndex: int = 0xFF
    nextSiblingIndex: int = 0xFF

    @property
    def name(self) -> str:
        return f"{self.skeletonName}Limb_{self.index:03}"

    @property
    def children(self) -> list[OOTBaseLimb]:
        return self._children

    @children.setter
    def children(self, children: list[OOTBaseLimb]) -> None:
        self._children = children
        self.firstChildIndex = self._children[0].index

    def addChild(self, child: OOTBaseLimb, index: int | None = None) -> None:
        index = index if index is not None else len(self.children)

        self.children.insert(index, child)
        self.setLinks()

    def recursiveChildren(self) -> list[OOTBaseLimb]:
        children = []
        for child in self.children:
            children.append(child)
            children.extend(child.children)
        return children

    def setLinks(self) -> None:
        if len(self.children) > 0:
            self.firstChildIndex = self.children[0].index
        for i in range(len(self.children)):
            if i < len(self.children) - 1:
                self.children[i].nextSiblingIndex = self.children[i + 1].index
            self.children[i].setLinks()

    def getList(self, limbList: list[OOTBaseLimb]) -> None:
        limbList.append(self)
        for child in self.children:
            child.getList(limbList)

    def getNumLimbs(self):
        numLimbs = 1
        for child in self.children:
            numLimbs += child.getNumLimbs()
        return numLimbs

    @abstractmethod
    def getNumDLs(self) -> int:
        ...

    @abstractmethod
    def typeData(self) -> str:
        ...

    def toC(self) -> str:
        data = f"{self.typeName} "

        data += (
            self.name
            + " = { "
            + "{ "
            + str(int(round(self.translation[0])))
            + ", "
            + str(int(round(self.translation[1])))
            + ", "
            + str(int(round(self.translation[2])))
            + " }, "
            + str(self.firstChildIndex)
            + ", "
            + str(self.nextSiblingIndex)
            + ", "
        )

        data += self.typeData()

        data += " };\n"

        return data


@dataclass
class StandardLimb(OOTBaseLimb):
    DL: GfxList | OOTDLReference | None = None
    _: KW_ONLY
    typeName: str = "Standard"

    def getNumDLs(self) -> int:
        numDLs = 0
        if self.DL is not None:
            numDLs += 1
        for child in self.children:
            numDLs += child.getNumDLs()

        return numDLs

    def typeData(self) -> str:
        data = ""

        data += self.DL.name if self.DL is not None else "NULL"

        # data += " };\n"

        return data


@dataclass
class LODLimb(OOTBaseLimb):
    DL: GfxList | OOTDLReference | None = None
    lodDL: GfxList | OOTDLReference | None = None
    _: KW_ONLY
    typeName: str = "Lod"

    @property
    def dLists(self) -> list[GfxList | OOTDLReference | None]:
        return [self.DL, self.lodDL]

    @dLists.setter
    def dLists(self):
        ...

    def getNumDLs(self) -> int:
        numDLs = 0
        if self.DL is not None or self.lodDL is not None:
            numDLs += 1

        for child in self.children:
            numDLs += child.getNumDLs()

        return numDLs

    def typeData(self) -> str:
        data = ""
        data += f"{{ {self.DL.name if self.DL is not None else 'NULL'}, "
        data += f"{self.lodDL.name if self.lodDL is not None else 'NULL'} }}"
        return data


@dataclass
class SkinLimb(OOTBaseLimb):
    _segment: SkinAnimData | GfxList | OOTDLReference | None = None
    segmentType: LimbSkinType = LimbSkinType.EMPTY
    _: KW_ONLY
    typeName: str = "Skin"

    def __post_init__(self) -> None:
        self.segment = self._segment

    @property
    def segment(self) -> SkinAnimData | GfxList | OOTDLReference | None:
        return self._segment

    @segment.setter
    def segment(self, value: SkinAnimData | GfxList | OOTDLReference | LimbSkinType | None) -> None:
        if isinstance(value, LimbSkinType):
            self._segment = None
            self.segmentType = value
        else:
            self._segment = value
            if isinstance(value, GfxList) or (isinstance(value, OOTDLReference)):
                self.segmentType = LimbSkinType.SKIN_LIMB_TYPE_NORMAL
            elif isinstance(value, FMesh):
                self.segmentType = LimbSkinType.SKIN_LIMB_TYPE_ANIMATED

    def getNumDLs(self) -> int:
        numDLs = 0

        if self.segmentType in (LimbSkinType.SKIN_LIMB_TYPE_ANIMATED, LimbSkinType.SKIN_LIMB_TYPE_NORMAL):
            numDLs += 1

        for child in self.children:
            numDLs += child.getNumDLs()
        return numDLs

    def typeData(self) -> str:
        data = ""

        data += f"{self.segmentType}, "

        match self.segmentType:
            case LimbSkinType.EMPTY | LimbSkinType.SKINNED:
                data += "NULL"
            case LimbSkinType.SKIN_LIMB_TYPE_ANIMATED:
                data += f"&{self.segment.name}"
            case LimbSkinType.SKIN_LIMB_TYPE_NORMAL:
                # assert (type(self.segment) is GfxList or type(self.segment) is OOTDLReference)
                data += self.segment.name

        return data


@dataclass
class OOTBaseSkeleton:
    name: str
    limbType: type[OOTBaseLimb]
    limbRoot: OOTBaseLimb | None = None
    segmentID = None

    def addChild(self, child: OOTBaseLimb) -> None:
        self.limbRoot = child

    def createLimbList(self) -> list[OOTBaseLimb]:
        if self.limbRoot is None:
            return []

        limbList = []
        self.limbRoot.getList(limbList)
        self.limbRoot.setLinks()
        return limbList

    def getNumLimbs(self) -> int:
        if self.limbRoot is not None:
            return self.limbRoot.getNumLimbs()
        else:
            return 0

    def limbsName(self) -> str:
        return f"{self.name}Limbs"

    @abstractmethod
    def headerData(self) -> CData:
        ...

    def toC(self) -> CData:
        limbData = CData()
        data = CData()

        if self.limbRoot is None:
            return data

        limbList = self.createLimbList()

        data.source += "void* " + self.limbsName() + "[" + str(self.getNumLimbs()) + "] = {\n"
        for limb in limbList:
            limbData.source += limb.toC()
            data.source += "\t&" + limb.name + ",\n"
        limbData.source += "\n"
        data.source += "};\n\n"

        data.append(self.headerData())

        for limb in limbList:
            name = f"{self.name}_{toAlnum(limb.boneName)}".upper()
            if limb.index == 0:
                data.header += f"#define {name}_POS_LIMB 0\n"
                data.header += f"#define {name}_ROT_LIMB 1\n"
            else:
                data.header += f"#define {name}_LIMB {limb.index + 1}\n"
        data.header += f"#define {self.name.upper()}_NUM_LIMBS {len(limbList) + 1}\n"

        limbData.append(data)

        return limbData


@dataclass
class StandardSkeleton(OOTBaseSkeleton):
    def headerData(self) -> CData:
        data = CData()

        data.source += f"SkeletonHeader {self.name} = {{ {self.limbsName()}, {self.getNumLimbs()} }};\n\n"
        data.header = f"extern SkeletonHeader {self.name};\n"

        return data


@dataclass
class FlexSkeleton(OOTBaseSkeleton):
    def headerData(self) -> CData:
        data = CData()
        data.source += (
            f"FlexSkeletonHeader {self.name} = {{ {self.limbsName()}, {self.getNumLimbs()}, {self.getNumDLs()} }};\n\n"
        )
        data.header = f"extern FlexSkeletonHeader {self.name};\n"
        return data

    def getNumDLs(self) -> int:
        if self.limbRoot is not None:
            return self.limbRoot.getNumDLs()
        else:
            return 0


class OOTSkeleton:
    def __init__(self, name):
        self.name = name
        self.segmentID = None
        self.limbRoot: OOTLimb | None = None
        self.hasLOD = False

    def createLimbList(self):
        if self.limbRoot is None:
            return []

        limbList = []
        self.limbRoot.getList(limbList)
        self.limbRoot.setLinks()
        return limbList

    def getNumDLs(self):
        if self.limbRoot is not None:
            return self.limbRoot.getNumDLs()
        else:
            return 0

    def getNumLimbs(self):
        if self.limbRoot is not None:
            return self.limbRoot.getNumLimbs()
        else:
            return 0

    def isFlexSkeleton(self):
        if self.limbRoot is not None:
            return self.limbRoot.isFlexSkeleton()
        else:
            return False

    def limbsName(self):
        return self.name + "Limbs"

    def toC(self):
        limbData = CData()
        data = CData()

        if self.limbRoot is None:
            return data

        limbList = self.createLimbList()
        isFlex = self.isFlexSkeleton()

        data.source += "void* " + self.limbsName() + "[" + str(self.getNumLimbs()) + "] = {\n"
        for limb in limbList:
            limbData.source += limb.toC(self.hasLOD)
            data.source += "\t&" + limb.name() + ",\n"
        limbData.source += "\n"
        data.source += "};\n\n"

        if isFlex:
            data.source += (
                "FlexSkeletonHeader "
                + self.name
                + " = { "
                + self.limbsName()
                + ", "
                + str(self.getNumLimbs())
                + ", "
                + str(self.getNumDLs())
                + " };\n\n"
            )
            data.header = "extern FlexSkeletonHeader " + self.name + ";\n"
        else:
            data.source += (
                "SkeletonHeader " + self.name + " = { " + self.limbsName() + ", " + str(self.getNumLimbs()) + " };\n\n"
            )
            data.header = "extern SkeletonHeader " + self.name + ";\n"

        for limb in limbList:
            name = (self.name + "_" + toAlnum(limb.boneName)).upper()
            if limb.index == 0:
                data.header += "#define " + name + "_POS_LIMB 0\n"
                data.header += "#define " + name + "_ROT_LIMB 1\n"
            else:
                data.header += "#define " + name + "_LIMB " + str(limb.index + 1) + "\n"
        data.header += "#define " + self.name.upper() + "_NUM_LIMBS " + str(len(limbList) + 1) + "\n"

        limbData.append(data)

        return limbData


class OOTDLReference:
    def __init__(self, name: str):
        self.name = name

    def toSohXML(self):
        return f'<SkinAnimatedLimbData TotalVtxCount="{self.totalVtxCount}" LimbModifCount="{self.limbModifCount}" LimbModifications="{self.limbModifications}" DisplayList="{self.dlist}"/>'

    def toC(self):
        pass

    def initVertexList(self):
        vertexList = [Vtx([0, 0, 0], [0, 0], [0, 0, 0])] * (self.totalVtxCount or 0)
        return vertexList

    def toVertexList(self, limbs):
        vertexList = self.initVertexList

        for modif in self.limbModifications:
            verts = modif.toVtxDict(limbs)
            for idx, vtx in verts:
                vertexList[idx] = vtx

        return vertexList


class OOTLimb:
    def __init__(
        self,
        skeletonName: str,
        boneName: str,
        index: int,
        translation: mathutils.Vector,
        segment: GfxList | OOTDLReference | SkinAnimData | None,
        lodDL: GfxList | OOTDLReference,
        limbType: str = "Standard",
        segmentType: LimbSkinType = LimbSkinType.EMPTY,
        # skinAnimatedLimbData: SkinAnimatedLimbData = None,
    ):
        self.skeletonName = skeletonName
        self.boneName = boneName
        self.translation = translation
        self.firstChildIndex = 0xFF
        self.nextSiblingIndex = 0xFF
        # self.DL = DL
        self.lodDL = lodDL
        self.limbType = limbType
        self.segmentType = segmentType

        self.isFlex = False
        self.index = index
        self.children = []
        self.inverseRotation = None

        self.DL = None
        self.skinAnimatedLimbData = None

        if limbType == "Skin":
            match self.segmentType:
                # case LimbSkinType.UNSKINNED | LimbSkinType.SKINNED:
                #     self.DL = None
                #     self.skinAnimatedLimbData = None
                case LimbSkinType.SKIN_LIMB_TYPE_ANIMATED:
                    self.skinAnimatedLimbData = segment
                case LimbSkinType.SKIN_LIMB_TYPE_NORMAL:
                    self.DL = segment
        else:
            self.DL = segment

    def toC(self, isLOD):
        if not isLOD:
            data = "StandardLimb "
        else:
            data = "LodLimb "

        data += (
            self.name()
            + " = { "
            + "{ "
            + str(int(round(self.translation[0])))
            + ", "
            + str(int(round(self.translation[1])))
            + ", "
            + str(int(round(self.translation[2])))
            + " }, "
            + str(self.firstChildIndex)
            + ", "
            + str(self.nextSiblingIndex)
            + ", "
        )

        if not isLOD:
            data += self.DL.name if self.DL is not None else "NULL"
        else:
            data += (
                "{ "
                + (self.DL.name if self.DL is not None else "NULL")
                + ", "
                + (self.lodDL.name if self.lodDL is not None else "NULL")
                + " }"
            )

        data += " };\n"

        return data

    def name(self):
        return self.skeletonName + "Limb_" + format(self.index, "03")

    def getNumLimbs(self):
        numLimbs = 1
        for child in self.children:
            numLimbs += child.getNumLimbs()
        return numLimbs

    def getNumDLs(self):
        numDLs = 0
        if self.DL is not None or self.lodDL is not None:
            numDLs += 1

        for child in self.children:
            numDLs += child.getNumDLs()

        return numDLs

    def isFlexSkeleton(self):
        if self.isFlex:
            return True
        else:
            for child in self.children:
                if child.isFlexSkeleton():
                    return True
            return False

    def getList(self, limbList):
        # Like ootProcessBone, this must be in depth-first order to match the
        # OoT SkelAnime draw code, so the bones are listed in the file in the
        # same order as they are drawn. This is needed to enable the programmer
        # to get the limb indices and to enable optimization between limbs.
        limbList.append(self)
        for child in self.children:
            child.getList(limbList)

    def setLinks(self):
        if len(self.children) > 0:
            self.firstChildIndex = self.children[0].index
        for i in range(len(self.children)):
            if i < len(self.children) - 1:
                self.children[i].nextSiblingIndex = self.children[i + 1].index
            self.children[i].setLinks()
        # self -> child -> sibling
