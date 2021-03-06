"""
sc_get_gs.py
program to:
1) view and capture an image of sediment
2) get site and sample info from the user
3) save image to file with the site and sample in the file name
4) crop and make greyscale and save another file
5) calculate grain size distribution and save results to text file
6) write summary statistics of the distribution to text file

Written by:
Daniel Buscombe, Oct 2013
Grand Canyon Monitoring and Research Center, U.G. Geological Survey, Flagstaff, AZ 
please contact:
dbuscombe@usgs.gov

SYNTAX:
python sc_get_gs.py

REQUIREMENTS:
python
kivy (http://kivy.org/#home)
python imaging library (https://pypi.python.org/pypi/PIL)
scipy (https://pypi.python.org/pypi/scipy)
numpy (https://pypi.python.org/pypi/numpy)
joblib (https://pypi.python.org/pypi/joblib)

"""

import kivy
kivy.require('1.7.2')
 
from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.camera import Camera
from kivy.uix.button import Button
from kivy.core.window import Window
from kivy.uix.scatter import Scatter
from kivy.uix.textinput import TextInput

import Image, os, time
import numpy as np
import scipy.signal as sp
from joblib import Parallel, delayed

################################################################
############## SUBFUNCTIONS ####################################
################################################################
def ascol( arr ):
    '''
    reshapes row matrix to be a column matrix (N,1).
    '''
    if len( arr.shape ) == 1: arr = arr.reshape( ( arr.shape[0], 1 ) )
    return arr

################################################################
def iseven(n):
   """Return true if n is even."""
   return n%2==0

################################################################
def isodd(n):
   """Return true if n is odd."""   
   return not iseven(n)

################################################################
def rescale(dat,mn,mx):
    """
    rescales an input dat between mn and mx
    """
    m = min(dat.flatten())
    M = max(dat.flatten())
    return (mx-mn)*(dat-m)/(M-m)+mn

################################################################
def pad2nxtpow2(A,ny):
    """
    zero pad numpy array up to next power 2
    """
    base2 = np.fix(np.log(ny)/np.log(2) + 0.4999)
    Y = np.zeros((1,ny+(2**(base2+1)-ny)))
    np.put(Y, np.arange(ny), A)
    return np.squeeze(Y)

################################################################
def cropcentral(im):
    """
    crop image to central box
    """
    size = min(im.size)
    originX = im.size[0] / 2 - size / 2
    originY = im.size[1] / 2 - size / 2
    cropBox = (originX, originY, originX + size, originY + size)
    return im.crop(cropBox) 

################################################################
def log2(x):
     """
     utility function to return (integer) log2
     """
     return int( np.log(float(x))/ np.log(2.0)+0.0001 )

################################################################
class Cwt:
    """
    Base class for continuous wavelet transforms
    Implements cwt via the Fourier transform
    Used by subclass which provides the method wf(self,s_omega)
    wf is the Fourier transform of the wavelet function.
    Returns an instance.
    """

    fourierwl=1.00

################################################################
    def _log2(self, x):
        # utility function to return (integer) log2
        return int( np.log(float(x))/ np.log(2.0)+0.0001 )

################################################################
    def __init__(self, data, largestscale=1, notes=0, order=2, scaling='linear'):
        """
        Continuous wavelet transform of data

        data:    data in array to transform, length must be power of 2
        notes:   number of scale intervals per octave
        largestscale: largest scale as inverse fraction of length
                 of data array
                 scale = len(data)/largestscale
                 smallest scale should be >= 2 for meaningful data
        order:   Order of wavelet basis function for some families
        scaling: Linear or log
        """
        ndata = len(data)
        self.order = order
        self.scale = largestscale
        self._setscales(ndata,largestscale,notes,scaling)
        self.cwt = np.zeros((self.nscale,ndata), np.complex64)
        omega = np.array(range(0,ndata/2)+range(-ndata/2,0))*(2.0*np.pi/ndata)
        datahat = np.fft.fft(data)
        self.fftdata = datahat
        #self.psihat0=self.wf(omega*self.scales[3*self.nscale/4])
        # loop over scales and compute wvelet coeffiecients at each scale
        # using the fft to do the convolution
        for scaleindex in range(self.nscale):
            currentscale = self.scales[scaleindex]
            self.currentscale = currentscale  # for internal use
            s_omega = omega*currentscale
            psihat = self.wf(s_omega)
            psihat = psihat *  np.sqrt(2.0*np.pi*currentscale)
            convhat = psihat * datahat
            W    = np.fft.ifft(convhat)
            self.cwt[scaleindex,0:ndata] = W 
        return

################################################################    
    def _setscales(self,ndata,largestscale,notes,scaling):
        """
        if notes non-zero, returns a log scale based on notes per ocave
        else a linear scale
        notes!=0 case so smallest scale at [0]
        """
        if scaling=="log":
            if notes<=0: notes=1 
            # adjust nscale so smallest scale is 2 
            noctave = self._log2( ndata/largestscale/2 )
            self.nscale = notes*noctave
            self.scales = np.zeros(self.nscale,float)
            for j in range(self.nscale):
                self.scales[j] = ndata/(self.scale*(2.0**(float(self.nscale-1-j)/notes)))
        elif scaling=="linear":
            nmax = ndata/largestscale/2
            self.scales = np.arange(float(2),float(nmax))
            self.nscale = len(self.scales)
        else: raise ValueError, "scaling must be linear or log"
        return
 
################################################################   
    def getdata(self):
        """
        returns wavelet coefficient array
        """
        return self.cwt

################################################################
    def getcoefficients(self):
        return self.cwt

################################################################
    def getpower(self):
        """
        returns square of wavelet coefficient array
        """
        return (self.cwt* np.conjugate(self.cwt)).real

################################################################
    def getscales(self):
        """
        returns array containing scales used in transform
        """
        return self.scales

################################################################
    def getnscale(self):
        """
        return number of scales
        """
        return self.nscale

################################################################
# wavelet classes    
class Morlet(Cwt):
    """
    Morlet wavelet
    """
    _omega0 = 6.0 #5.0
    fourierwl = 4* np.pi/(_omega0+ np.sqrt(2.0+_omega0**2))

################################################################
    def wf(self, s_omega):
        H = np.ones(len(s_omega))
        n = len(s_omega)
        for i in range(len(s_omega)):
            if s_omega[i] < 0.0: H[i] = 0.0
        # !!!! note : was s_omega/8 before 17/6/03
        xhat = 0.75112554*( np.exp(-(s_omega-self._omega0)**2/2.0))*H
        return xhat

################################################################
def column(matrix, i):
    """
    return a column from a matrix
    """
    return [row[i] for row in matrix]

################################################################
def writeout( item, sz, pdf, mnsz, srt, sk, kurt, resolution ):
    """
    writes results to file
    """

    with open(item+'_psd.txt', 'w') as f:
     np.savetxt(f, np.hstack((ascol(sz),ascol(pdf))), delimiter=', ', fmt='%s')   
    print 'psd results saved to ',item,'_psd.txt'

    title = item+ "_summary.txt"
    fout = open(title,"w")

    fout.write("%"+time.strftime('%l:%M%p %z on %b %d, %Y')+"\n") 

    fout.write("% grain size results ..."+"\n")
    fout.write("% resolution:\n")
    fout.write(str(resolution)+"\n")
    fout.write('% mean grain size:'+"\n")
    fout.write(str(mnsz)+"\n")
    fout.write('% sorting :'+"\n")
    fout.write(str(srt)+"\n")
    fout.write('% skewness :'+"\n")
    fout.write(str(sk)+"\n")
    fout.write('% kurtosis :'+"\n")
    fout.write(str(kurt)+"\n")

    fout.close()
    print 'summary results saved to ',title

################################################################
def processimage( region, density, resolution, numproc ):
    """
    main processing program which reads image and calculates grain size distribution
    """

    # convert to numpy array
    region = np.array(region)
    nx, ny = np.shape(region)

    # resize image so it is half the size (to reduce computational time)
    #useregion= np.array(imresize(region,(( nx/2, ny/2 )))).T
    #nx, ny = np.shape(useregion)
    mn = min(nx,ny)

    mult = 6*int(float(100*(1/np.std(region.flatten()))))

    useregion = region

    wavelet = Morlet
    maxscale = 3
    notes = 8 # suboctaves per octave
    #scaling = "log" #or "linear"
    scaling = "log"

    # for smoothing:
    l2nx = np.ceil( np.log(float(ny))/ np.log(2.0)+0.0001 )
    npad = int(2**l2nx)
    k = np.r_[0.:np.fix(npad)/2]
    k = k*((2.*np.pi)/npad)
    kr = -k[::-1]
    kr = kr[:np.asarray(np.fix((npad-1)/2), dtype=np.int)]
    k2 = np.hstack((0,k,kr))**2

    # each row is treated using a separate queued job
    print 'analysing every ',density,' rows of a ',nx,' row image'
    d = Parallel(n_jobs = numproc, verbose=0)(delayed(parallel_me)(column(np.asarray(useregion), k), ny, wavelet, maxscale, notes, scaling, k2, npad) for k in range(1,nx-1,density))

    A = column(np.asarray(useregion), 1)
    # detrend the data
    A = sp.detrend(A)
    # pad detrended series to next power 2 
    Y = pad2nxtpow2(A,ny)
    # Wavelet transform the data
    cw = wavelet(Y,maxscale,notes,scaling=scaling)     
    cwt = cw.getdata()
    # get rid of padding before returning
    cwt = cwt[:,0:ny] 
    scales = cw.getscales()    
    del A, Y, cw, cwt

    Or1 = np.reshape(d, (-1,np.squeeze(np.shape(scales)))).T
    # column-wise variance, scaled
    varcwt1 = np.var(Or1,axis=1) 
    varcwt1 = varcwt1/np.sum(varcwt1)
    
    svarcwt = varcwt1*sp.kaiser(len(varcwt1),mult)
    svarcwt = svarcwt/np.sum(svarcwt)
    
    index = np.nonzero(scales<ny/3)
    scales = scales[index]
    svarcwt = svarcwt[index]
    scales = scales*1.5

    # get real scales by multiplying by resolution (mm/pixel)
    scales = scales*resolution

    mnsz = np.sum(svarcwt*scales)
#    print "mean size = ", mnsz 

    srt = np.sqrt(np.sum(svarcwt*((scales-mnsz)**2)))
#    print "stdev = ",srt 

    sk = (sum(svarcwt*((scales-mnsz)**3)))/(100*srt**3)
#    print "skewness = ",sk

    kurt = (sum(svarcwt*((scales-mnsz)**4)))/(100*srt**4)
#    print "kurtosis = ",kurt

    return scales, svarcwt, mnsz, srt, sk, kurt

################################################################
def cropcentral(im):
    originX = 180
    originY = 1
    cropBox = (originX, originY, originX + 900, originY + 700)
    return im.crop(cropBox)

################################################################

def parallel_me(A, ny, wavelet, maxscale, notes, scaling, k2, npad):
   # extract column from image
#   A = column(np.asarray(useregion), k)
   # detrend the data
   A = sp.detrend(A)
   # pad detrended series to next power 2 
   Y = pad2nxtpow2(A,ny)
   # Wavelet transform the data
   cw = wavelet(Y,maxscale,notes,scaling=scaling)     
   cwt = cw.getdata()
   # get rid of padding before returning
   cwt = cwt[:,0:ny] 
   scales = cw.getscales()
   # get scaled power spectrum
   wave = np.tile(1/scales, (ny,1)).T*(np.absolute(cwt)**2)

   # smooth
   twave = np.zeros(np.shape(wave)) 
   snorm = scales/1.
   for ii in range(0,np.shape(wave)[0]):
       F = np.exp(-.5*(snorm[ii]**2)*k2)
       smooth = np.fft.ifft(np.squeeze(F)*np.squeeze(np.fft.fft(wave[ii,:],npad)))
       twave[ii,:] = smooth[:ny].real

   # store the variance of real part of the spectrum
   dat = np.var(twave,axis=1)
   dat = dat/sum(dat)
   return np.squeeze(dat.T) #O1


################################################################
############## MAIN PROGRAM ####################################
################################################################

class SedimentCamApp(App):
          # Function to take a screenshot
          def doscreenshot(self,*largs):
                outname='site_'+self.site.text+'sample_'+self.sample.text+'_im%(counter)04d.png'
                Window.screenshot(name=outname)
                # get newest file
                filelist = os.listdir(os.getcwd())
                filelist = filter(lambda x: not os.path.isdir(x), filelist)
                newest = max(filelist, key=lambda x: os.stat(x).st_mtime)
                # read that file in as greyscale, crop and save under new name
                im = Image.open(newest).convert("L")
                region = cropcentral(im)
                newfile = newest.split('.')[0]+'_g.png'
                region.save(newfile)

                sz, pdf, mnsz, srt, sk, kurt = processimage( region, 10, 1, 8 )
                writeout( newfile, sz, pdf, mnsz, srt, sk, kurt, 1 )

          def build(self):

                # create a floating layout as base
                camlayout = FloatLayout(size=(600, 600))
                cam = Camera()        #Get the camera
                cam=Camera(resolution=(1024,1024), size=(300,300))
                cam.play=True         #Start the camera
                camlayout.add_widget(cam)

                button=Button(text='Take Picture',size_hint=(0.12,0.12))
                button.bind(on_press=self.doscreenshot)
                camlayout.add_widget(button)    #Add button to Camera Layout

                # create a text input box for site name
                s1 = Scatter(size_hint=(None, None), pos_hint={'x':.01, 'y':.9})
                self.site = TextInput(size_hint=(None, None), size=(150, 50), multiline=False)

                # create a text input box for sample (flag) name
                s2 = Scatter(size_hint=(None, None), pos_hint={'x':.01, 'y':.8})
                self.sample = TextInput(size_hint=(None, None), size=(150, 50), multiline=False)

                # add the text widgets to the window
                s1.add_widget(self.site)
                camlayout.add_widget(s1) 
                s2.add_widget(self.sample)
                camlayout.add_widget(s2) 

                return camlayout
             
if __name__ == '__main__':
    SedimentCamApp().run() 
 

