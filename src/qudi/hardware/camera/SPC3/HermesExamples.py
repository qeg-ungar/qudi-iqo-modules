import numpy as np
from spc import SPC3
import matplotlib.pyplot as plt
import matplotlib

matplotlib.use('TkAgg')


def ExampleLive():
    plt.close('all')
    h = SPC3(SPC3.CameraMode.NORMAL)
    num_counters = 2
    h.SetCameraPar(100, 1, 1000, num_counters, SPC3.State.DISABLED, SPC3.State.DISABLED, SPC3.State.DISABLED)
    h.ApplySettings()
    h.LiveSetModeON()

    plot_img = plt.imshow(np.zeros((32, 64)))
    plt.set_cmap('gray')

    for k in range(1000):
        live_frames = h.LiveGetImg()
        counter1_frame = live_frames[0]
        # frames[0] contains live image for counter 1 (shown below)
        # frames[1] contains live image for counter 2
        plt.clim(np.min(counter1_frame), np.max(counter1_frame))
        plt.title('frame {}'.format(k))
        plot_img.set_data(counter1_frame)
        plt.pause(0.010)


def ExampleLiveSubArray():
    plt.close('all')
    h = SPC3(SPC3.CameraMode.NORMAL)
    num_rows = 8
    num_pixels = 32 * num_rows
    h.SetCameraParSubArray(1000, 1, 300, SPC3.State.DISABLED, num_pixels)
    h.ApplySettings()
    h.LiveSetModeON()

    plot_img = plt.imshow(np.zeros((32, num_rows)))
    plt.set_cmap('gray')

    for k in range(1000):
        live_frames = h.LiveGetImg()
        counter1_frame = live_frames[0]
        # frames[0] contains live image for counter 1 (shown below)
        # frames[1] contains live image for counter 2
        plt.clim(np.min(counter1_frame), np.max(counter1_frame))
        plt.title('frame {}'.format(k))
        plot_img.set_data(counter1_frame)
        plt.pause(0.010)


def ExampleBackgroundSubtraction():
    plt.close('all')
    h = SPC3(SPC3.CameraMode.NORMAL)
    h.SetCameraPar(4096, 1000, 100, 1, SPC3.State.DISABLED, SPC3.State.DISABLED, SPC3.State.DISABLED)
    h.ApplySettings()

    input('Close the camera shutter and press ENTER...')

    h.SnapPrepare()
    h.SnapAcquire()
    BackgroundImg = h.AverageImg(1)

    input('Open the camera shutter and press ENTER...')

    h.SetBackgroundSubtraction(SPC3.State.DISABLED)
    h.ApplySettings()
    h.SnapPrepare()
    h.SnapAcquire()
    AvgImg_sub_off = h.AverageImg(1)

    h.SetBackgroundImg(BackgroundImg)
    h.SetBackgroundSubtraction(SPC3.State.ENABLED)
    h.ApplySettings()
    h.SnapPrepare()
    h.SnapAcquire()
    AvgImg_sub_on = h.AverageImg(1)

    plt.close('all')
    fig, axes = plt.subplots(nrows=3, ncols=1)
    fig.tight_layout()

    # Plot the data on each subplot using imshow
    axes[0].imshow(BackgroundImg)
    axes[0].set_title('Background acquisition')

    axes[1].imshow(AvgImg_sub_off)
    axes[1].set_title('Image acquisition - without background subtraction')

    axes[2].imshow(AvgImg_sub_on)
    axes[2].set_title('Image acquisition - with background subtraction')
    plt.show()


def ExampleSnap():
    plt.close('all')
    num_frames = 100
    h = SPC3(SPC3.CameraMode.NORMAL)
    num_counters = 1
    h.SetCameraPar(100, num_frames, 300, num_counters, SPC3.State.DISABLED, SPC3.State.DISABLED,
                   SPC3.State.DISABLED)
    h.ApplySettings()
    h.SnapPrepare()
    h.SnapAcquire()

    frames = h.SnapGetImageBuffer()[0]  # frames of counter 1

    plt.close('all')
    fig, axes = plt.subplots(nrows=3, ncols=3)
    fig.tight_layout()

    # plot first 9 frames
    for i in range(3):
        for j in range(3):
            axes[i][j].imshow(frames[i * 3 + j])
            axes[i][j].set_title('frame {}'.format(i * 3 + j))
    plt.show()


def ExampleFile():
    plt.close('all')
    h = SPC3(SPC3.CameraMode.NORMAL)
    h.SetCameraPar(100, 300, 300, 1, SPC3.State.DISABLED, SPC3.State.DISABLED, SPC3.State.DISABLED)

    h.ApplySettings()
    h.SnapPrepare()
    h.SnapAcquire()

    h.SaveImgDisk(1, 300, 'full_acquisition', SPC3.OutFileFormat.HERMES_FILEFORMAT)
    counter = 1
    is_double = False
    h.SaveAveragedImgDisk(counter, 'avg_acquisition', SPC3.OutFileFormat.HERMES_FILEFORMAT, is_double)

    # read the file and extract data from the full acquisition
    frames, file_header = SPC3.ReadSPC3DataFile('full_acquisition.hrm')
    counter1_frames = frames[0]

    plt.close('all')
    fig, axes = plt.subplots(nrows=3, ncols=3)
    fig.tight_layout()

    # plot first 9 frames
    for i in range(3):
        for j in range(3):
            axes[i][j].imshow(counter1_frames[i * 3 + j])
            axes[i][j].set_title('frame {}'.format(i * 3 + j))
    plt.show()


def ExampleContinuousFile():
    h = SPC3(SPC3.CameraMode.NORMAL)
    h.SetCameraPar(100, 300, 300, 1, SPC3.State.DISABLED, SPC3.State.DISABLED, SPC3.State.DISABLED)
    h.ApplySettings()
    h.ContAcqToFileStart('continuous_acq')

    req_bytes = 1e3 * 2048 * 2  # 1 kframes
    tot_bytes = 0
    while tot_bytes < req_bytes:
        tot_bytes = tot_bytes + h.ContAcqToFileGetMemory()

        progress = 100. * tot_bytes / req_bytes
        print('progress = {:.1f}%'.format(progress), end='\r')
    h.ContAcqToFileStop()

    # read the file and extract data from the full acquisition
    frames, file_header = SPC3.ReadSPC3DataFile('continuous_acq.hrm')
    counter1_frames = frames[0]

    plt.close('all')
    fig, axes = plt.subplots(nrows=3, ncols=3)
    fig.tight_layout()

    # plot first 9 frames
    for i in range(3):
        for j in range(3):
            axes[i][j].imshow(counter1_frames[i * 3 + j])
            axes[i][j].set_title('frame {}'.format(i * 3 + j))
    plt.show()


def ExampleContinuousInMemory():
    plt.close('all')
    h = SPC3(SPC3.CameraMode.NORMAL)
    h.SetCameraPar(100, 1, 1000, 1, SPC3.State.DISABLED, SPC3.State.DISABLED, SPC3.State.DISABLED)
    h.ApplySettings()
    h.ContAcqToMemoryStart()

    plot_img = plt.imshow(np.zeros((32, 64)))

    print('Downloading frames')

    data = np.empty((0,), dtype=np.uint8)  # will be promoted to uint16 if ContAcqToMemoryGetBuffer gives 16-bit data

    total_num_values = 100 * 1000
    while data.size < total_num_values:
        data = np.concatenate((data, h.ContAcqToMemoryGetBuffer()))
        progress = 100. * data.size / total_num_values
        print('progress = {:.1f}%'.format(progress), end='\r')

    h.ContAcqToMemoryStop()

    # trim end of data that may contain an incomplete frame
    # or not the same number of frames per counter

    data = data[0: h.num_counters * h.num_pixels * int(np.floor((data.size / (h.num_counters * h.num_pixels))))]

    # get frames of counter 1
    frames = SPC3.BufferToFrames(data, h.num_pixels, h.num_counters)[0]

    plt.close('all')
    fig, axes = plt.subplots(nrows=3, ncols=3)
    fig.tight_layout()

    # plot first 9 frames of counter 1
    for i in range(3):
        for j in range(3):
            axes[i][j].imshow(frames[i * 3 + j])
            axes[i][j].set_title('frame {}'.format(i * 3 + j))
    plt.show()


def ExampleFlim():
    plt.close('all')

    h = SPC3(SPC3.CameraMode.NORMAL)

    FLIM_steps = 1000
    FLIM_shift = 1
    FLIM_start = -500
    Length = 10

    h.SetFlimState(SPC3.State.ENABLED)
    flim_frame_time = h.SetFlimPar(FLIM_steps, FLIM_shift, FLIM_start, Length)
    print('flim_frame_time = {}'.format(flim_frame_time))

    h.SetTriggerOutState(SPC3.State.ENABLED)
    h.ApplySettings()

    h.ContAcqToMemoryStart()

    print('Downloading frames')

    data = np.empty((0,), dtype=np.uint8)  # will be promoted to uint16 if ContAcqToMemoryGetBuffer gives 16-bit data

    total_num_values = FLIM_steps * 2048
    while data.size < total_num_values:
        data = np.concatenate((data, h.ContAcqToMemoryGetBuffer()))
        progress = 100. * data.size / total_num_values
        print('progress = {:.1f}%'.format(progress), end='\r')

    h.ContAcqToMemoryStop()

    frames = SPC3.BufferToFrames(data, h.num_pixels, h.num_counters)[0]

    frames = frames[0:FLIM_steps]

    fig, axes = plt.subplots(nrows=2, ncols=1)
    fig.tight_layout()

    mean_frame = np.mean(frames, 0)
    axes[0].imshow(mean_frame)
    axes[0].set_title('Mean Frame')

    flim_period = 20  # nanoseconds
    plot_time = np.arange(FLIM_steps) * (flim_period / FLIM_steps)
    step_counts = [np.sum(f) for f in frames]

    axes[1].plot(plot_time, step_counts)
    axes[1].set_xlabel('Time [ns]')
    axes[1].set_ylabel('Counts [a.u.]')
    axes[1].set_title('FLIM mode - total frame counts per gate step')
    plt.show()


def ExampleOpenCv():
    try:
        import cv2
    except ModuleNotFoundError:
        print('OpenCV Python bindings not found.')
        return

    h = SPC3(SPC3.CameraMode.NORMAL)
    h.SetCameraPar(100, 1, 1000, 1, False, False, False)
    h.ApplySettings()
    h.LiveSetModeON()

    print('Press Esc to stop the acquisition.')
    while True:
        hermes_img = h.LiveGetImg()[0] # extract live image of counter 1

        # normalize image and convert it to a 8-bit image
        img_8bit = ((255.0 * hermes_img) / np.max(hermes_img)).astype(np.uint8)

        # enlarge image 10x (without antialiasing)
        gray = cv2.resize(img_8bit, (0, 0), fx=10, fy=10, interpolation=cv2.INTER_NEAREST)

        thresh_low = np.min(gray) + 0.05 * (np.max(gray) - np.min(gray))
        thresh_high = np.min(gray) + 0.95 * (np.max(gray) - np.min(gray))

        # convert 8-bit grayscale image to BGR image
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        img[gray < thresh_low] = (255, 0, 0)  # blue
        img[gray > thresh_high] = (0, 0, 255)  # red

        cv2.imshow('img', img)

        # wait for 'Esc' key to stop
        if cv2.waitKey(50) & 0xff == 27:
            return

    cv2.destroyAllWindows()


if __name__ == '__main__':
    ExampleLive()
