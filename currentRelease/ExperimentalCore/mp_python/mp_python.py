#! /usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function  # compatibilité python 3.0
#te
import os
import sys
# Add I-Simpa folder in lib path
from os.path import dirname
libpath = dirname(os.path.abspath(__file__ + "/../../"))
sys.path.append(libpath)
#libpath='c:\program files\i-simpa'
print("syspath : ",sys.path)


try:
    import libsimpa as ls
except ImportError:
    print("Couldn't find libsimpa in " + libpath, file=sys.stderr)
    exit(-1)
import kdtree
import sauve_recsurf_results
from build_recsurf import GetRecepteurSurfList
import coreConfig as cc
import shutil
import glob
import time
import math
import xml.dom.minidom  as xmlWriter
from build_recsurf import GetRecepteurSurfList
import numpy as np

try:
    import h5py
except ImportError:
    print("h5py python module not found, cannot read hdf5 files. See www.h5py.org", file=sys.stderr)
    exit(-1)

try:
    import numpy
except ImportError:
    print("numpy python module not found", file=sys.stderr)
    exit(-1)


# todo under windows look for
# HKEY_LOCAL_MACHINE\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Octave-4.2.0

class ReceiverSurf:
    def __init__(self, idrs, faceid, x, y, z):
        self.coords = (x, y, z)
        self.idrs = idrs
        self.isSurfReceiver = True
        self.idrp = None
        self.faceid = faceid
        self.spl = []


    def __iter__(self):
        return self.coords.__iter__()

    def __len__(self):
        return 3

    def __getitem__(self, item):
        return self.coords[item]

    def __str__(self):
        return self.coords.__str__()

class ReceiverPunctual:
    def __init__(self, idrp, x, y, z):
        self.coords = (x, y, z)
        self.isSurfReceiver = False
        self.idrp = idrp
        self.spl = []

    def __iter__(self):
        return self.coords.__iter__()

    def __len__(self):
        return 3

    def __getitem__(self, item):
        return self.coords[item]

    def __str__(self):
        return self.coords.__str__()

def to_vec3(vec):
    return ls.vec3(vec[0], vec[1], vec[2])

def to_array(vec):
    return [vec[0], vec[1], vec[2]]

def square_dist(v1, v2):
    return sum([(v1[axis] - v2[axis])**2 for axis in range(len(v1))])


def schroeder_to_impulse(schroeder):
    # In octave schroeder seems to be truncated so we remove last entry
    return schroeder[:-1] - schroeder[1:]

def get_a_coefficients(p, p1, p2, p3, p4):
    """
        Compute the interpolation coefficient of a point into a tetrahedron
        ex: getACoefficients([2,2,0.2], [1,1,0],[3,2,0], [2,4,0], [2,2.5,3])
        source: Journal of Electronic Imaging / April 2002 / Vol. 11(2) / 161
    :param p: Any point (x,y,z)
    :param p1: p1 of tetrahedron (x,y,z)
    :param p2: p2 of tetrahedron (x,y,z)
    :param p3: p3 of tetrahedron (x,y,z)
    :param p4: p4 of tetrahedron (x,y,z)
    :return (a1,a2,a3,a4) coefficients. If point is inside of tetrahedron so all coefficient are greater than 0
    """
    left_mat = numpy.append(numpy.swapaxes(numpy.array([p1, p2, p3, p4]), 0, 1), numpy.ones((1, 4)), axis=0)
    right_mat = numpy.append(numpy.reshape(p, (3, 1)), [1])
    return numpy.dot(numpy.linalg.inv(left_mat), right_mat)

def GetNumStepBySource(pos, coreconf):
    """
        Return the time step number of the incoming impulse for each sound source
    """
    ret_tab = {}
    if coreconf.const["with_direct_sound"]:
        for src in coreconf.sources_lst:
            dist = (pos - src.pos).length()
            ret_tab[src.id] = int(math.floor(dist / (coreconf.const["cel"] * coreconf.const['timestep'])))
    return ret_tab



# Find octave program utility
def which(program):
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None


def write_input_files(cbinpath, cmbinpath, outfolder):
    """
     Import 3D model
     XML volume index to python index
    :param cbinpath:
    :param cmbinpath:
    :param sources_lst:
    :param outfolder:
    :return: dictionary of loaded data or None if failed
    """
    ret = {}
    idVolumeIndex = {}

    modelImport = ls.ioModel()
    
    #-------------Code modifié----------------
    if isinstance(modelImport, bytes):
       modelImport = modelImport.decode('utf-8')
    if isinstance(cbinpath, bytes):
        cbinpath = cbinpath.decode('utf-8')
    if isinstance(cmbinpath, bytes):
        cmbinpath = cmbinpath.decode('utf-8')
    #-------------FIN Code modifié------------
    
    if not ls.CformatBIN().ImportBIN(modelImport, cbinpath):
        print("Error can not load %s model !\n" % cbinpath)
        return None

    # Import 3D mesh file builded from tetgen output
    mesh_import = ls.CMBIN().LoadMesh(cmbinpath)
    if not mesh_import:
        print("Error can not load %s mesh model !\n" % cmbinpath)
        return None

    # Write NODES file
    XYZ=[]
    for node in mesh_import.nodes:
        #f.write('{0:>15} {1:>15} {2:>15}'.format(*(node[0], node[1], node[2])) + "\n")
        XYZ.append([node[0], node[1], node[2]])
    XYZ=np.array(XYZ)
    
    ret["model"] = modelImport
    ret["mesh"] = mesh_import
    # Write elements file
    el=[]
    for tetra in mesh_import.tetrahedres:
        volindex = idVolumeIndex.get(tetra.idVolume)
        if volindex is None:
            volindex = len(idVolumeIndex) + 1
            idVolumeIndex[tetra.idVolume] = len(idVolumeIndex) + 1
        #f.write('{0:>6} {1:>6} {2:>6} {3:>6} {4:>6}'.format(*(
        #tetra.vertices[0] + 1, tetra.vertices[1] + 1, tetra.vertices[2] + 1, tetra.vertices[3] + 1,
        #volindex)) + "\n")
        el.append([
        tetra.vertices[0] + 1, tetra.vertices[1] + 1, tetra.vertices[2] + 1, tetra.vertices[3] + 1,
        volindex])
    el=np.array(el)


    return ret,el,XYZ

def process_output_files(outfolder, coreconf, import_data, nodes,Vecps,tetrahedrons, NbEV):
    # sound velocity
    n1, n2 = 0,0
    c0 = 342.0
    rhoco2 = 1.2 * c0 * c0
    # Read mesh file information from python
    
    #--------------modifs 10/07/2024---------------
    # mesh_path = os.path.join(outfolder, "scene_elements.txt")
    # if os.path.exists(mesh_path):
    # mesh_data = h5py.File(mesh_path, "r")
    # nodes = mesh_data["topo"]["value"]["XYZ"]["value"].value.transpose()
    # rooms = set(mesh_data["topo"]["value"]["TetDOF"]["value"].keys()) - {"dims"}
    # tetrahedrons = numpy.concatenate([mesh_data["topo"]["value"]["TetDOF"]["value"][key]["value"].value.astype(int).transpose() for key in rooms])
    # print("tetraèdres : ", tetrahedrons, len(tetrahedrons))
    if len(tetrahedrons)==1:
        tetrahedrons=tetrahedrons[0]
    elif len(tetrahedrons)==2:
        tetrahedrons=np.concatenate((tetrahedrons[0],tetrahedrons[1]), axis=0)
    else:
        tetrahedrons2=np.concatenate((tetrahedrons[0],tetrahedrons[1]), axis=0)
        for k in range(len(tetrahedrons)-2):
            tetrahedrons2=np.array(tetrahedrons2)
            # print("tetraèdre : ", len(tetrahedrons2), tetrahedrons2)
            # print("concat : ", np.array(tetrahedrons[2+k]))
            tetrahedrons2=np.concatenate((tetrahedrons2,np.array(tetrahedrons[2+k])), axis=0)
            # print("final :", len(tetrahedrons2), tetrahedrons2)
        tetrahedrons=tetrahedrons2
    #--------------FIN modifs 10/07/2024-----------
    #print("Vecps = ", Vecps)
    # Create spatial index for receivers points
    receivers_index = kdtree.create(dimensions=3)
    # For each surface receiver
    pt_count = 0
    for idrs, surface_receivers in coreconf.recsurf.items():
        # For each vertex of the grid
        for faceid, receiver in enumerate(surface_receivers.GetSquaresCenter()):
            receivers_index.add(ReceiverSurf(idrs, faceid, receiver[0], receiver[1], receiver[2]))
            pt_count += 1
    # For each punctual receiver
    for idrp, rp in coreconf.recepteursponct.items():
        receivers_index.add(ReceiverPunctual(idrp, rp["pos"][0], rp["pos"][1], rp["pos"][2]))
        pt_count += 1

    receivers_index.rebalance()

    # Open data files
    if coreconf.const["stationary"]:
        # result_matrix = [numpy.array(h5py.File(os.path.join(outfolder, "scene_WStaFields" + str(freq) + ".hdf5"))["xx"]["value"]["b"]["value"]) for freq in
        #              coreconf.const["frequencies"]]
        result_matrix = Vecps
    else:
        #result_matrix = [numpy.array(h5py.File(os.path.join(outfolder, "scene_WInstaFields" + str(freq) + ".hdf5"))["xx"]["value"]["b"]["value"]) for freq in
                     #coreconf.const["frequencies"]]
        result_matrix = Vecps
        #coreconf.time_step = float(h5py.File(os.path.join(outfolder, "scene_WInstaFields" + str(coreconf.const["frequencies"][0]) + ".hdf5"))["xx"]["value"]["a"]["value"].value)
        #coreconf.time_step = dt
    # print("taille result:", len(result_matrix), len(result_matrix[0]), len(result_matrix[0][0]))
    # print("type result:", type(result_matrix), type(result_matrix[0]), type(result_matrix[0][0]))
    last_perc = 0
    for idTetra in range(0, len(tetrahedrons)):
        # print(f"tetrahedrons[{idTetra}]:", tetrahedrons[idTetra])
        verts = [tetrahedrons[idTetra][idvert] - 1 for idvert in range(4)]
        # print("taille verts:", len(verts))
        # print("type verts:", type(verts))
        # print("verts:", verts)
        # print("test:",len(result_matrix[0][:, 100]))
        p1 = to_vec3(nodes[verts[0]])
        p2 = to_vec3(nodes[verts[1]])
        p3 = to_vec3(nodes[verts[2]])
        p4 = to_vec3(nodes[verts[3]])
        p = (p1+p2+p3+p4) / 4
        rmax = math.ceil(max([square_dist(p, p1), square_dist(p, p2), square_dist(p, p3), square_dist(p, p4)]))
        # Fetch receivers in the tetrahedron
        # nearest_receivers = receivers_index.search_nn_dist([p[0], p[1], p[2]], rmax)
        nearest_receivers = receivers_index.search_nn_dist([p[0], p[1], p[2]], rmax)
        tetra_values = [[numpy.ones(4) for idvert in range(4)] for idfreq in range(NbEV)]
        if len(nearest_receivers) > 0:
            tetra_values = [
                [result_matrix[idfreq][verts[idvert]] for idvert in range(4)] for
                idfreq in range(NbEV)]
        #print("tetra values : ", tetra_values)
        # nearest_receivers = [receiver for receiver in res if square_dist(receiver, p) <= rmax]
        new_perc = int((idTetra / float(len(tetrahedrons))) * 100)
        if new_perc != last_perc:
            #print("Export receivers %i %%" % new_perc)
            last_perc = new_perc
        # Compute coefficient of the receiver point into the tetrahedron
        for receiver in nearest_receivers:
            coefficient = get_a_coefficients(to_array(receiver), nodes[verts[0]], nodes[verts[1]], nodes[verts[2]], nodes[verts[3]])
            if coefficient.min() > -1e-6:
                #print("1")
                #print("len = ",len(coreconf.const["frequencies"]))
                # Point is inside tetrahedron
                for id_freq in range(NbEV):
                   # print("2")
                    # closest freq id using all frequencies
                    #current_frequency_id = coreconf.const["allfrequencies"].index(min(coreconf.const["allfrequencies"], key=lambda x: abs(x - coreconf.const["frequencies"][id_freq])))
                    # For each frequency compute the interpolated value
                    interpolated_value = coefficient[0] * tetra_values[id_freq][0] + \
                                         coefficient[1] * tetra_values[id_freq][1] + \
                                         coefficient[2] * tetra_values[id_freq][2] + \
                                         coefficient[3] * tetra_values[id_freq][3]

                    # Compute direct field timestep
                    #steps = GetNumStepBySource(to_vec3(receiver), coreconf)
                    # If the receiver belongs to a surface receiver add the value into it
                    if receiver.isSurfReceiver:
                        #print("3")
                        # Look for sound source
                        coreconf.recsurf[receiver.idrs].face_power[receiver.faceid].append(
                            interpolated_value)
                        #print(f"surface {receiver.idrs}, face {receiver.faceid} : ", coreconf.recsurf[receiver.idrs].face_power[receiver.faceid])
                        if receiver.idrs == 6805:
                            n1+=1
                        else :
                            n2+=1
    print("n1 = ", n1, "n2 = ", n2)
    print("End export receivers values")

def write_config_file(coreConf, outputdir):
    with open(os.path.join(outputdir, "Input_parameters.m"), "w") as f:
        f.write("Temperature=%f;\n" % coreConf.const["temperature_celsius"])
        f.write("Humidity=%f;\n" % coreConf.const["humidite"])
        f.write("Pressure=%f;\n" % coreConf.const["pression"])


def run_model(el,XYZ,coreConf,libpath):
    sys.path.append(libpath + '/Lib/import_frequencies')
    import Room_Natural_Frequencies_ao2
    nodes, Vecps, tetrahedrons, NbEV=Room_Natural_Frequencies_ao2.main(el,XYZ,coreConf)
    return nodes, Vecps, tetrahedrons, NbEV

def main(call_python=True):
    # find core folder
    scriptfolder = sys.argv[0][:sys.argv[0].rfind(os.sep)] + os.sep
    # Read I-SIMPA XML configuration file
    coreconf = cc.coreConfig(sys.argv[1])


    
    #------------------modif code---------------------
    working_directory = coreconf.paths["workingdirectory"]
    if isinstance(working_directory, bytes):
       working_directory = working_directory.decode('utf-8')
    outputdir = os.path.join(working_directory, "core")
    #------------------FIN modif code-----------------
    
    #outputdir = os.path.join(coreconf.paths["workingdirectory"], "core")
    if not os.path.exists(outputdir):
        os.mkdir(outputdir)
    # Translation CBIN 3D model and 3D tetrahedra mesh into Octave input files
    import_data,el,XYZ = write_input_files(os.path.join(coreconf.paths["workingdirectory"], coreconf.paths["modelName"]), os.path.join(coreconf.paths["workingdirectory"], coreconf.paths["tetrameshFileName"]),
                      outputdir)

    coreconf.recsurf = GetRecepteurSurfList(coreconf, import_data["model"], import_data["mesh"])
    # Copy octave script to working dir
    matscript_folder = os.path.join(os.path.abspath(os.path.join(os.path.realpath(__file__), os.pardir)), "script")
    files = glob.iglob(os.path.join(matscript_folder, "*.py"))
    print(os.path.join(matscript_folder, "*.py"))
    for filep in files:
        if os.path.isfile(filep):
            shutil.copy2(filep, outputdir)
    # Write configuration file
    write_config_file(coreconf, outputdir)

    
    #--------------Modifs code 08/07/2024-------
    script_name = "Room_Natural_Frequencies_ao2.py"
    #script_path = os.path.join("C:/Program Files/I-SIMPA/core/mp_python/Script" , script_name)
    #print("script_path = ", script_path)
    #sys.path.append('C:/ProgramData/anaconda3/Lib/venv/scripts/nt')
    #command = ["--no-window-system", "C:/ProgramData/anaconda3/Lib/venv/scripts/nt"]
    #print("Run " + " ".join(command))
    deb = time.time()
    nodes, Vecps, tetrahedrons, NbEV=run_model(el,XYZ,coreconf, libpath)
    process_output_files(outputdir, coreconf, import_data,nodes,Vecps,tetrahedrons, NbEV)
    
    sauve_recsurf_results.SauveRecepteurSurfResults(coreconf, NbEV)
    print("Execution in %.2f seconds" % ((time.time() - deb) / 1000.))
    #--------------FIN Modifs code--------------
    # for nodes in coreconf.recsurf.items():
    #     print("noeuds :", nodes[1].vertices, nodes[1].faceindex, nodes[1].face_power, nodes[1].index, nodes[1].label, nodes[1].props)
    #process_output_files(outputdir, coreconf, import_data, resultsModificationLayers)

if __name__ == '__main__':
    main(sys.argv[-1] != "noexec")
