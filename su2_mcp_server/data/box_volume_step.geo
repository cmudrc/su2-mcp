SetFactory("OpenCASCADE");
Merge "model.step";

// Healing / sewing
Geometry.OCCFixDegenerated = 1;
Geometry.OCCFixSmallEdges  = 1;
Geometry.OCCFixSmallFaces  = 1;
Geometry.OCCSewFaces       = 1;
Geometry.OCCMakeSolids     = 1;
Coherence;

// Mesh sizing (keep coarse for first success)
Mesh.CharacteristicLengthMin = 1000;
Mesh.CharacteristicLengthMax = 6000;

Mesh.Optimize       = 1;
Mesh.OptimizeNetgen = 1;

// --- Build aircraft as a solid from the imported surfaces (THIS is the key) ---
s_air[] = Surface{:};
Surface Loop(100) = {s_air[]};
Volume(100) = {100};
Coherence;

v_air[] = {100};

// --- Farfield box ---
xmin = -80000; ymin = -80000; zmin = -80000;
dx   = 160000; dy   = 160000; dz   = 160000;
Box(1) = {xmin, ymin, zmin, dx, dy, dz};

// --- Fluid = box minus aircraft ---
v_fluid[] = BooleanDifference{ Volume{1}; Delete; }{ Volume{v_air[]}; Delete; };
Coherence;

Physical Volume("FLUID") = {v_fluid[]};

// --- Boundary tagging ---
s_bnd[] = Boundary{ Volume{v_fluid[]}; };

eps = 1e-3;
s_xmin[] = Surface In BoundingBox {xmin-eps,     ymin-eps,     zmin-eps,     xmin+eps,     ymin+dy+eps,  zmin+dz+eps};
s_xmax[] = Surface In BoundingBox {xmin+dx-eps,  ymin-eps,     zmin-eps,     xmin+dx+eps,  ymin+dy+eps,  zmin+dz+eps};
s_ymin[] = Surface In BoundingBox {xmin-eps,     ymin-eps,     zmin-eps,     xmin+dx+eps,  ymin+eps,     zmin+dz+eps};
s_ymax[] = Surface In BoundingBox {xmin-eps,     ymin+dy-eps,  zmin-eps,     xmin+dx+eps,  ymin+dy+eps,  zmin+dz+eps};
s_zmin[] = Surface In BoundingBox {xmin-eps,     ymin-eps,     zmin-eps,     xmin+dx+eps,  ymin+dy+eps,  zmin+eps};
s_zmax[] = Surface In BoundingBox {xmin-eps,     ymin-eps,     zmin+dz-eps,  xmin+dx+eps,  ymin+dy+eps,  zmin+dz+eps};

s_farfield[] = {s_xmin[], s_xmax[], s_ymin[], s_ymax[], s_zmin[], s_zmax[]};
s_wall[] = s_bnd[];
s_wall[] -= s_farfield[];

Physical Surface("FARFIELD") = {s_farfield[]};
Physical Surface("WALL")     = {s_wall[]};

// Clean duplicates before 3D tetra (helps "overlapping facets")

// Use Netgen (Algorithm3D = 4) to avoid HXT overlapping facets failures
Mesh.Algorithm3D = 4; // Netgen


Mesh 2;
Coherence Mesh;
Mesh 3;

