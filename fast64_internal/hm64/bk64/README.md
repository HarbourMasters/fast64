# Banjo-Kazooie

Imports and exports Banjo-Kazooie models and animations. A model can be written as an o2r resource family for the [Lighthouse](https://github.com/HarbourMasters/Lighthouse) PC port, or as a single `.bin` for the ROM hacking tools. Set the game to BK64 in the Fast64 tab to see these tools.

### Tool Locations (BK64)
Everything is in the 3D view sidebar under the BK64 tab. Press N if the sidebar is hidden.

- **Model Exporter** writes a model, or a level's two halves together. Format, scale, rigging and the default draw layer are set here.
- **Animations** exports the actions on an armature, and imports one onto it.
- **Model Importer** brings in a model, its skeleton alone, or a whole level picked by name.
- **Mesh Tools** change the mesh you have selected: Promote Materials To 2 Cycle, Split Mesh At Bones, Select Loose Vertices, Toggle Collision Only and Add Texture Scroll.

Bone settings are in the properties editor under the bone tab, and material settings under the material tab.

### What A BK Model Is
Every model is one display list drawing from one vertex list, cut into chunks. A geo layout says which chunk draws under which bone, and a bone table gives each bone a rest position and an ID that animations address. A static prop is those four things and nothing else.

Everything past that is optional. A model can also carry collision triangles, collision shapes, a mesh list of vertex groups the game moves itself, animated textures, and the camera gates a level uses. Each has its own section below, and a model carrying none of them is still a model.

### What Gets Exported
In o2r a model is not a single file, but a set of resources sharing a base path. Exporting to `models/mymodel` writes:

- `mymodel`, the header, bounds, display list, bone table and collision.
- `mymodel_VTX`, the vertex buffer.
- `mymodel_GEO`, the geo layout that binds display list ranges to bones.
- `mymodel_tex_0`, `mymodel_tex_1` and so on, one per texture.

Don't rename these or split them across folders. The port finds them by appending the suffixes to the model's own resource path. Rename a sibling and the port won't find it. Exporting as `.bin` puts all of it in the one file instead.

A level is two of these families rather than one, `_OPA` and `_XLU`. "Export Level Halves", below, writes both.

### Scene Setup
Set the game to BK64. This also sets the microcode to F3DEX/LX, which Banjo's display lists use, and fills in the world defaults. The defaults describe the RDP state the game has already set before a model's display list runs. Because a material only writes the settings that differ from them, a vanilla model's display list is nearly empty.

The defaults are stored on the scene's world, and the scene needs one. A file started from Blender's General template has one. An empty file or an imported scene may not, and setting the game mode then has nowhere to write them. The export stops with a message if the world is missing or its defaults have been changed. Pick BK64 again in the game dropdown to refill them.

Your model should be upright with +Z up, facing -Y. The exporter converts to the N64's Y up on the way out. A static model takes its own rotation and scale with it. An armature doesn't, since a rig goes out in armature space, so apply what you turn on one. SM64 rigs in particular are often authored lying along +X, since SM64's geolayout root applies the rotation for them. Rotate those upright before exporting.

Blender To BK Scale converts Blender units to BK units, and defaults to 100 as it does for SM64 and MK64. One Blender unit becomes that many BK units, so at 100 Banjo stands 1.38 units tall in Blender and a Jinjo 1.04. Those are heights, not scale values. Either importer fills the scale in, and any value round trips as long as import and export agree.

Animation Scale multiplies the translation channel of any animation played on the model. It only matters for animated models, where either importer fills it in for you when replacing a vanilla model.

Resource Path is where the model is stored inside the archive. Use anything you like for a new model, or a vanilla model's own path to replace it.

### Materials
Materials must be **2 cycle**. Every model the game draws is set up in 2 cycle mode, and the render modes it provides put the real blending in the second cycle. A 1 cycle material never reaches that second cycle. It draws with the pass-through blender the table puts in the first, and anything meant to be see-through comes out solid. Materials created while in BK64 mode are 2 cycle already, so this only comes up on a mesh brought in from elsewhere, where 1 cycle presets are common. The export fails and lists any that aren't. "Promote Materials To 2 Cycle" converts every material on the selected mesh at once. The second cycle it adds only passes the first cycle's result through, leaving what you set up in the first alone and nothing new to configure.

Meshes must use F3D materials, as they do everywhere else in Fast64. If you have a model with Principled BSDF materials, use the Principled BSDF to F3D conversion operator to convert them.

Shading comes from vertex color. The game loads no lights for a model. A vanilla model carries its shading baked into its vertices instead.

The vertex color's alpha channel only reaches the output if the alpha combiner takes SHADE. "BK Vertex Colored Texture" holds alpha at 1, so painting that channel does nothing there. Use "BK Vertex Colored Texture Transparent", which takes shade alpha in the first cycle and scales it by the primitive color's alpha in the second, giving one fade control over the whole material. "BK Vertex Colored Texture Cutout" takes the texture's alpha instead, for foliage and railings that are vertex shaded.

No preset sets a render mode, and none should. A chunk jumps into the render mode table the game builds instead, picked by its Draw Layer. Ticking Set Render Mode writes a mode into the display list after that jump, which overrides it and takes the actor's depth behavior away from the game.

The viewport previews a material the way its render mode preset describes, so a cutout clips and a transparent one blends while you work. That preset is preview only. What the game actually renders with comes from Draw Layer, below. The transparent presets set that for you, so the two start out agreeing. Nothing holds them together afterwards: move a material to the opaque layer and it still previews blended while it ships solid.

Force Unlit Shade, on by default, does that baking. It calculates what the RSP would have shaded each vertex, ambient plus every light facing it, from the material's light colors and directions and the vertex normal. The result goes to the vertex color. An unlit material already has a color there and passes it through untouched. A mesh painted by hand or baked in Blender exports as it looks.

Reflective materials need the Reflective (Env Map) option. It sets up the reflection matrix that G_TEXTURE_GEN environment mapping needs. The lighting flag has to stay on for it, with no lights loaded, because that flag transforms the normal the reflection samples. A reflective material therefore keeps both the flag and its vertex normals through the export, where every other material has its shading baked down into vertex color.

Trilinear Mipmap is the other geo type flag and is off by default. With it on, any 32x32 RGBA16 material whose combiner blends two texels gets a mip pyramid written. A texture imported from the game writes back the levels it came in with, which Rare drew by hand. Edit the base and the levels are filtered from it instead.

Both boxes only apply to a model you built yourself. An imported one keeps the flags it arrived with, and the panel greys the boxes out and shows the value as Imported Geo Type. Set that to 0 to take the boxes back. A level's two halves usually disagree, which is why the flags are kept per object rather than per scene.

Draw Layer is Opaque for solid geometry and Translucent for blended. A model doesn't set a render mode directly. The game builds a table of render modes from whether the actor wants depth writing, depth compare or neither, and the model picks an entry from that table. Depth behavior stays with the game. If a model overrides it, other things in the world lose their depth test against that model.

Default Draw Layer on the export panel is what a material takes when its own is From Scene, so it applies to everything you haven't set explicitly. Faces using a different layer become their own chunk. A solid body with a see-through visor exports as one model with two chunks on one bone.

#### Draw Order
Materials export in the order of the object's material slots, and the game draws them in that order. Where two surfaces overlap and neither writes depth, the one drawn later is the one you see. Moving a material down the list brings its faces out in front of the ones above it.

A model built from several objects sorts by object name first, since the export walks the root's children in name order. Material slots then order the faces within each object.

### Textures
Fast64 converts textures to native N64 formats and the exporter writes them through untouched. RGBA16, RGBA32, CI4, CI8, I4, I8, IA4, IA8 and IA16 are all supported. BK stores a texture's width and height as a single byte each. Neither can exceed 255. The export fails with a message instead of truncating.

A texture also has to fit TMEM, which holds 4KB, or 2KB for a CI format since the palette takes the rest. The biggest that fit:

- RGBA32: 32x32, 16x64, 8x128
- RGBA16, IA16 and CI8: 32x64, 64x32, 16x128, 8x256
- I8, IA8 and CI4: 64x64, 32x128, 128x32, 16x256
- I4 and IA4: 64x128, 128x64, 32x256, 256x32

Halving one side lets the other double, and the material tab shows what a texture uses against that budget. Going over isn't an error. Fast64 keeps the image whole and writes it as an HD texture: a smaller tile stands in for it in the display list, with the scales beside it saying how much bigger the real image is. Only an o2r export can carry those scales. A `.bin` stores its images as bare bytes with nowhere to record them, and refuses.

A paletted texture is split in two. The image goes out as its own `_tex_<i>` sibling while its palette goes into the model's texture blob, where the game points segment 2. Since Fast64 picks CI8 automatically for an image with few enough colors, a model brought in from elsewhere is often paletted already. This is supported and needs no changes.

Large Texture Mode is not supported. It splits a mesh into pieces that each load part of an image, but BK binds a texture whole, by index for a resource and by offset for a `.bin`. Scale the image down to fit TMEM instead.

Tile settings default to wrap. A model imported from a format with no equivalent loses whatever it was authored with. Any face whose UVs reach past the tile edge then samples from the far side of the texture instead of stopping at it. That shows up as streaks and smears across otherwise flat surfaces. Set Clamp on S and T for those materials.

### Animated Textures
A material's texture can cycle through a set of frames, which is how the Beauty Machine's screen flickers and how lightning flashes. Set Animated Texture on the material, then list every frame under it starting with the one the material already samples. Frames Per Second is what it sounds like, and vanilla runs between 4 and 15.

Every frame shares one size and one format, and that format is RGBA16, RGBA32 or IA8. A CI4 or CI8 frame would have to animate its palette alongside the image, and the exporter refuses rather than writing something the game reads past the end of.

The game doesn't swap textures. It stacks the frames end to end in the model's texture data and slides a pointer along them, and that's why every frame has to be the same size. Four slots exist and slot 0 is the only one vanilla ever uses. Use another only if a model animates more than one texture at once.

### Exporting A Model
For a static model such as a prop or a set piece, select the mesh and click "Export BK Model". Nothing else is needed.

For a rigged model select the armature instead, and any mesh parented to it is included. There are two ways to attach geometry to a bone:

1. Vertex groups, the usual skinned setup. A vertex group named after a bone binds to that bone.
2. Parenting an entire mesh object to a bone (Ctrl+P -> Bone). The whole object becomes that bone's chunk.

Banjo's skinning is rigid either way: there are no vertex weights, and each vertex follows exactly one bone. A seam is closed by a face's corners following different bones, not by blending weights. The Rigging setting picks how the model records which vertex follows which bone, and the game supports two methods.

**Split At Bones** gives every bone its own display list and draws each under its own matrix. A face can stay welded across a bone and its parent, the one seam the game's skinning blends. Anywhere else, the mesh has to be cut.

The export refuses an illegal weld instead of cutting it for you. Use "Split Mesh At Bones" to make the cuts in the scene, where you can check them.

**Bind Vertices** keeps the mesh whole and writes a table beside it naming the bone each vertex follows. Before drawing, the game walks that table, takes each entry's rest position, puts it through that bone's matrix, and writes the result into the vertices the entry lists. One triangle can then reach across a joint with its corners on different bones, closing the seam without modeling around it. Gruntilda, Boggy and Gobi are built this way.

A vertex no bone weights is left out of that table and holds its rest pose while the model moves. The export warns and names the coordinate, and "Select Loose Vertices" picks them out in the scene.

The exporter doesn't mix the two, and no vanilla model does either. Pick one per model. Everything else is the same: the bone table goes out unchanged and animations play on either.

Setting a Geo Type on a bone only takes effect with Split At Bones, apart from Reference Point. The other nodes pick between the geometry of different bones, and a bound model draws under none of them. A reference point draws nothing at all, and only reports where a joint landed. A bound model imported from the game does keep the selectors, sorts and reference points it arrived with, and round trips with them intact. With either method, only the first 128 bones in the table can own a display list, though bones past that still animate.

A model standing in for one of Banjo's transformations has to carry a Reference Point in slot 1 and another in slot 2. The game reads those two back to place the player's collision spheres, and every transformation model carries them. Without them both spheres collapse onto the player's own position and enemies pass through untouched. Put slot 1 around two thirds of the way up the model and slot 2 near the bottom, matching whichever model you replace.

Bound entries are keyed by rest position. Two vertices at exactly the same position go to the same bone regardless of their vertex groups. Move one of them if a joint needs them apart.

### Bone IDs
Animations address bones by ID, not by name or position, so the IDs your bone table carries decide which animations your model can play. Which way you set them depends on where the animations come from.

If the model brings its own, leave every BK Bone ID at 0 in the bone tab. The exporter numbers the table for you, and the animations you export from that armature address the numbers it chose.

If the model replaces a vanilla one and you want the game's existing animations to play on it, the IDs have to be the ones those animations already address. Import the original skeleton and build on it rather than numbering by hand. Getting this wrong is quiet. A channel aimed at an ID the table doesn't have moves nothing, with no crash, so the bone just holds its rest pose. A skeleton a few IDs out looks like a bad animation rather than a numbering mistake.

Two limits apply either way. An ID can't go past 0x6C, because the game indexes a fixed length table without checking, and the export refuses anything higher. And a model in an animated slot has to have a bone table at all, since the game crashes on one with no bones.

BK Bone Order is a different setting: where a bone sits in the exported table, not what addresses it. The skeleton importer fills it in so a vanilla model goes back out in its original order. On a model of your own, leave it at -1 and bones are ordered by name.

### Geo Nodes
As well as carrying geometry, a bone can act as a node in the geo layout, set by Geo Type in the bone tab.

**Selector** draws one of its child bones at a time. The game keeps a visibility value per appendage id and the selector reads it: 1 draws the first child, 2 the second, 0 draws nothing, and a negative value is a bit mask that draws several. Set Appendage ID to the id the game addresses, from 1 to 41, and parent one bone per option to the selector. Everything under an option bone goes with it.

The value isn't set automatically. An actor has to call `modelRender_setAppendageVisibility`. Until one does, a selector on a replacement model reads whatever was left in the slot unless the actor is changed to drive it. That requires a port change and can't be done by the exporter.

**Level Of Detail** draws what's under it only while the camera is between Near Distance and Far Distance of the joint, both in BK units. Far Distance has to be set or it never draws.

**Sort** orders its two child bones by which one is nearer the camera, for translucent halves that have to draw back to front. It takes exactly two.

**Draw Distance** skips everything under it when its box is off screen. The box is calculated from the geometry it guards, leaving nothing to set.

**Reference Point** reports where a joint is in a numbered slot the actor reads back, letting effects hang off a model. Set Point Slot to the number the actor expects. The point uses the bone's own matrix and lands wherever the bone's head is once the animation has moved it.

### Exporting An Animation
Pose the armature into an action, select it, and click "Export BK Animation". The action's own frame range is exported, one resource per action, to the Animation Path you set.

An animation is a set of curves addressed by bone ID and isn't tied to the model it was authored on. Any model whose table carries the same IDs can play it, which is how a replacement character plays the animations the game already has for it.

Animation Scale has to match the model the animation plays on. Because it multiplies the translation channels, the same values move a Jinjo and a Grunty different distances. The skeleton importer fills it in from whichever model you imported. If it's wrong, the rotations are still correct but the model slides the wrong distance.

Every channel is sampled once per frame and at half frames, then reduced to the fewest keys the game's reader can reproduce all of those samples from. Keys are flagged smooth. The game splines between them and a curve stays a curve. Rotation is stored in degrees and translation in animation units, both to a 64th. The exporter stops instead of writing a value larger than an s16 holds.

Translation resolution is limited by that 64th. One step is Animation Scale divided by 64, and nothing can land closer than that.

Hold Unanimated Bones, on by default, writes one resting key for every bone the action never moves. The game keeps one set of bone transforms per actor and only overwrites what the current animation mentions. A bone left out of a replacement animation keeps whatever the animation before it left there. Turning it off produces a smaller file that matches how vanilla animations are built, with that risk.

An animation loops by returning to progress zero. For anything that repeats, make the last frame's pose match the first.

"Export All Actions" writes every action in the file that has a curve on a bone of the selected armature, each named after the action and placed in the same folder as the Animation Path. Name the actions after the assets they replace to export a whole character's animation set at once. An action belonging to another rig is skipped, not exported as a model standing still.

### Collision
Scenery carries collision, characters don't.

Collision is set per material, under BK64 Collision in the material tab. Leave it at No Collision and those faces stay out of the list, which is how an ordinary model exports with none. Set it to Ground and Banjo can stand on those faces. Sound Type picks the footstep. Map Default and the numbered map sounds resolve through the map the model loads into, so a level replacing TTC gets sand. The named sounds are the same everywhere, and the Surface Flags cover slopes, hazards and the rest.

The triangles reference the model's own vertices. Collision costs a triangle list and nothing more.

Collision doesn't have to follow the mesh. Select a mesh and press Toggle Collision Only. It stops drawing but still collides: an invisible floor, a barrier across a gap, or a cheap box standing in for something detailed. Give every face a material with a Collision Type set, since a face with none is an error rather than a guess. The mesh goes out as extra vertices on the end of the model's own list, the way vanilla does it, and the model's radius grows to reach them.

Vanilla leans on this, the beehive and Mumbo's hut among them. Those come in as a `<name>_collision_only` mesh, so a re-export keeps them.

### Collision Shapes
Collision shapes are volumes the game tests against, separate from the collision triangles: boxes, cylinders and spheres, each able to ride a bone so it follows the animation. They decide whether one thing has touched another. A model with none is still collidable, just more roughly, since the game falls back to comparing a pair of plain spheres. The Grublin has five, on its head, both hands, its torso and its base.

Make one by putting an object under the model with a Shape custom property. Its own transform is the shape, so move, rotate and scale it to fit, and parent it to a bone to make it follow that bone. The first sphere does double duty as the volume swept against the world to decide whether a move is allowed, so put that one on the body. The cull radius tested before any shape is the model's own radius, the way every vanilla model has it, so there's nothing to set.

Set Hit Code to 255 unless something in the game needs to tell this shape from the others. The code is a label rather than a setting. 0 means every search skips the shape and 255 marks a plain volume, and small numbers are used where something is looking for one in particular. The jigsaw puzzle numbers its twenty pieces 1 to 20 so the game can ask which one you're standing on. Several shapes can share a code, so a search can ask whether a point is inside any of them.

An import brings shapes in as wire objects in a `<name>_collision_shapes` collection, marked Ignore Render so the model export leaves them alone, parented to the bone they name. Their undecoded fields ride along as custom properties. A map model uses the same structure for named regions the game queries by code. That is how Mad Monster Mansion knows to change the music when you step inside.

### Mesh Lists
A mesh list hands the game a set of vertex groups it animates by itself, with no actor driving them. Water that rises and falls, a light that flickers, a texture that scrolls. The sky, the map model, Bottles' bonus bookshelf and the jigsaw puzzle all carry one.

You don't pick the effect, the game does, by number. A mesh is a vertex group named `bk64_mesh_<uid>`, any group named that way goes back out as one, and the uid is what the game looks it up by. Which uid gets which effect is decided in the game's own code, so a mesh of yours animates only if you give it a uid the map already drives. Anything else needs a port change, not an export setting.

The uid carries the effect and its setting in one number. Which hundred it falls in picks the effect, and the rest is that effect's only parameter. Meshes 101 to 199 scroll their texture at a speed of uid minus 100. 200 to 299 flicker. 300 to 399 rise and fall, which is what water in a translucent half uses. The bands run to 1099, so anything above 399 is driven too.

Scrolling is the one you can set up without touching the port. Select the faces in edit mode, set Scroll Speed, and press "Add Texture Scroll". Speed 20 is what Gobi's Valley uses for its sand. Only the vertical texture coordinate moves, so the texture slides one way rather than drifting. Banjo's Backpack calls this Scroll Texture, and its Slow, Normal and Fast are speeds 6, 20 and 60.

Some uids are addresses for gameplay code rather than effects, and those you have to leave where they are. Gobi's Valley works out which sphinx tile Banjo is standing on by asking which mesh from 400 to 415 his position falls inside. Furnace Fun does the same from 401 to 495, and Mad Monster Mansion's shed and Treasure Trove Cove's castle ask over every mesh they have. Moving or renumbering one of those moves the region with it.

Two things to expect from a round trip. Membership rides on the vertices themselves, so a mesh exports with the vertices its group holds even where two meshes meet at one coordinate. And vanilla lists some vertices no triangle draws, which have no geometry to come in on. Re-exporting one of those models gives a slightly shorter list than the original.

### Importing A Model
"Import BK Model" reads a model resource or a `.bin`, and everything that came with it: mesh, UVs, vertex colors, textures, materials, the armature with its bone ids, and Animation Scale. The format is detected from the file, leaving nothing to set. Point Model File at a resource and keep its `_GEO`, `_VTX` and `_tex_<i>` siblings in the same folder; a `.bin` carries all of that already.

The mesh comes in as one object with a vertex group per bone, each vertex in the group of the bone that moves it. At a joint that's the parent bone, which is why posing the armature in Blender deforms the mesh the way the game does. Materials carry the texture, the combiner, the tile wrap modes and the collision the faces were drawn with.

The geo layout comes in with the model and goes back out on export: selectors, sorts, skinned seams and mipmapped materials all survive the round trip, along with your mesh edits. Geometry you add is drawn after the original layout, under whichever bone you weight it to.

Both rigging methods come in weighted. A Split At Bones model takes its weights from the layout, a bound one from its binding table. Gruntilda, Boggy and Gobi arrive posable, not as a bare mesh sitting beside an armature. The import sets Rigging to whichever of the two it found.

A Split At Bones model also remembers which chunk each face was drawn in, and that decides the bone the face draws under ahead of its weights. It's what keeps a vanilla model on its original bones through a round trip, but it means re-weighting an imported face doesn't move it. Delete the mesh's `hm64_bk64_source` attribute when you mean to re-rig, and the weights decide instead.

The collision fields describe every flag word vanilla ships. A word only a romhack sets comes in as Raw Flags and goes back out exactly as it arrived; clear that field to author the surface with the fields instead.

Imported materials come in unlit, apart from the reflective ones, because a BK model already carries its shading in its vertex colors and has nothing to calculate from the normals. Leave them unlit and a re-export keeps those colors exactly. Turn lighting on and the export bakes new shading from the material's lights instead, the right choice for a model you built yourself.

"Import BK Skeleton" does the same for the bones alone, when the mesh isn't wanted, and reads either format too.

### Importing An Animation
"Import BK Animation" reads an animation onto the selected armature as a new action, one keyframe per frame. Bones are matched by ID. Import the skeleton of the model the animation belongs to first. An animation naming an ID the rig doesn't have is refused rather than partly applied.

An imported animation is not a byte for byte copy of the original when exported again. It is exact on every whole frame, to within the translation step above. Between two frames it can differ by a couple of BK units. A key can only sit on a whole frame, and the original's curve leaves the line through its own per frame values by up to two degrees. Use this to read an animation to see how it moves, or to adjust it.

### Levels
A level's geometry is two models rather than one. The game loads an opaque half and a translucent half as separate resources, named for the level and which half they are: Treasure Trove Cove is `ASSET_146B_TTC_TREASURE_TROVE_COVE_OPA` and `ASSET_146C_TTC_TREASURE_TROVE_COVE_XLU`. Most maps have both halves, and some only the OPA.

The halves are not opaque and translucent geometry sorted by material. What the split decides is depth. OPA draws with depth writing on, XLU with depth compare only. Geometry in the second half is tested against what is already there, but never hides anything behind it. Each half then has its own opaque and translucent render modes, which a material's Draw Layer picks between. That is why an opaque model still carries translucent faces: they blend, and they still write depth. Which half a piece of geometry goes in is your call, the same choice Banjo's Backpack offers with its A and B model slots.

"Import BK Level" finds them by name, so point Level Folder at the folder you unpacked `bk.o2r` into and pick the level rather than hunting for asset ids. Halves brings in one or both, each as its own object, tagged with the half it came from.

A level's camera gates come in with it, as wire objects in a `<name>_camera_areas` collection. A CAMERA command in the geo layout names one by index and draws what hangs off it only while the camera is inside that box, or outside it. Move a box to move the gate. Delete one and everything it gated stops drawing.

Level Half on the export panel is that tag, and it reads From Materials until you say otherwise. An object whose materials are all one layer goes to that half whole. One holding both is cut along them, its translucent faces to the translucent half and the rest to the opaque one, so a level that came in as a single mesh doesn't have to be separated by hand. The panel says what it worked out for whichever object you have selected. Then "Export Level Halves" writes both models in one go.

A cut duplicates the vertices along the seam, because the two halves are separate models with their own vertex lists and nothing can be shared between them. Vertex groups come through it, so a mesh list spanning the boundary keeps its vertices on both sides.

Set Level Half outright to override the reading, and expect to for a vanilla level. Most of them keep translucent materials in their opaque half, where a face blends and still writes depth, so rebuilding one to its original layout means placing the halves yourself. From Materials sends those faces to the translucent half instead, which is the usual choice for glass and water in a level of your own. A level brought in with Halves set to Both is tagged outright and reads nothing off its materials.

The naming is handled for you. A level of your own gets `_OPA` and `_XLU` on the end of its Resource Path. A vanilla level gets the two names the port loads it by, and those differ by more than the suffix: Gobi's Valley is `ASSET_1474_GV_GOBIS_VALLEY_OPA` and `ASSET_1475_GV_GOBIS_VALLEY_XLU`. Point Resource Path at either one and both come out right.

Both halves go out every time, even an empty one, so replacing a level can't leave its old half standing. A half you gave no geometry is written as a model that draws nothing. An opaque only level still gets a translucent model, named from its own asset, for a hack meaning to add one. The map only draws it once its scene definition names an xlu asset.

Default Draw Layer is not that control. It says what a material on From Scene renders as, inside whichever half its object is in. Setting it to Translucent doesn't move faces between halves, it just puts every material you haven't set explicitly onto that layer, opaque geometry included.

### Replacing A Vanilla Model
To stand in for a vanilla model, your bone table needs to carry the bone IDs that model's animations address. Starting from the original skeleton is much safer than building one from scratch.

1. Set Model File to a model resource extracted from `bk.o2r`, then click "Import BK Model" to bring the original in, or "Import BK Skeleton" for the bones alone. Either way you get an armature with every bone's rest position, ID and parent, and Animation Scale filled in from that model.
    - Bone Length only affects how the bones are drawn in the viewport.
2. Fit your mesh to the imported armature and weight it to those bones.
3. Set Resource Path to the vanilla model's own path, for example `assets/model/ASSET_3C0_JINJO_BLUE`.
4. Export, pack, and drop the archive in the `mods` folder.

An actor whose model has a mesh list builds from it the moment it spawns, without checking. A stand-in that carries none crashes instead of just looking wrong. Keep the mesh groups the import creates and put your own geometry in them. Tee-hee, Mutie Snippet and the Twinklies are among these.

Bones come in at their original rest positions, and many sit exactly on their parent. These are still real table entries. Deleting one doesn't merge it into its neighbor, it removes a link from the chain and leaves whichever animation channel addressed that ID moving nothing.

### Getting It Into The Game
Format sets what is written, for animations as well as models. O2R writes the resource family described above, for the HarbourMasters ports. BK Model Binary writes a single `.bin` in the game's own format, which the ROM hacking tools read.

Textures are written differently for a `.bin`, because nothing outside the game reproduces the game's own shading. Fast64 materials keep their color in the light and let the combiner fold it into the texture. For a `.bin` the export bakes that fold into the pixels and leaves the vertex color neutral. Both of the shaded-texture setups Fast64 writes are handled: a flat tint, and the decal setup where the texture's alpha picks between a base color and the detail painted over it. A material that combines them some other way keeps its texture and vertex color unchanged.

A `.bin` takes RGBA16, RGBA32, CI4 and CI8, the four types the game's own header names. An o2r texture list also carries IA8, which is the format Lightning's animated frames are stored in.

The exporter writes loose resources into Export Folder. Turn that folder into an archive with Torch's packer. It zips the folder as it is, and the folder layout becomes the archive layout:

```
torch pack <export folder> <name>.o2r o2r
```

Drop the resulting `.o2r` in Lighthouse's `mods` folder.

### What Doesn't Come Back
Cull spheres, geo command 0x0E, are the one part of the format read past and not kept. They skip whatever hangs off them while the sphere is off screen. The import keeps the geometry under one but flattens the sphere away, and a model carrying one exports without it. Only ASSET_88E_CLANKER_CHAIN has any, and losing them draws the same picture for slightly more work. Use Draw Distance for a model of your own that needs culling.

### Common Issues
- The model renders black: a material still has lighting enabled and Force Unlit Shade is off.
- The model lies on its side: it wasn't authored with +Z up. Rotate it upright in Blender, and apply the rotation if it's an armature.
- It animates, but some limbs hold their rest pose: those bones' IDs aren't the ones the animation addresses. Import the original model's skeleton and match its IDs.
- An exported animation moves the model too far or not far enough: Animation Scale doesn't match the model it's playing on.
- Streaks or smears across flat surfaces: the tiles are set to wrap and some UVs reach past the tile edge. Set Clamp on S and T.
- The export still calls the mesh welded after you ran Split Mesh At Bones: a modifier is making the welded geometry. The split cuts the mesh itself, the export reads it with its modifiers applied. Apply them first.
- A re-weighted limb still follows the bone it had before: its faces kept the chunk they were imported in, which outranks their weights. Delete the mesh's `hm64_bk64_source` attribute.
- Limbs tear at the joints: the seam faces are cut, or welded across bones that aren't parent and child. Weld the seam to the joint's own bone pair, overlap the limbs, or switch to Bind Vertices.
- A single vertex stretches away from the model as it animates: it carries no weight to a bone's vertex group, so Bind Vertices leaves it behind at rest. Run Select Loose Vertices and weight what it finds.
- Select Loose Vertices finds nothing but the export still warned: a modifier is making that geometry. The export reads the mesh with its modifiers applied, and Boolean, Remesh, Skin and Geometry Nodes drop vertex groups.
