import cPickle
from ipdb import set_trace
from itertools import izip
import numpy as np
import os
import subprocess

from fisher_vectors.compute_sstats import get_sample_label
from fisher_vectors.compute_sstats import get_time_intervals
from fisher_vectors.compute_sstats import get_slice_number
from fisher_vectors.compute_sstats import parse_ip_type
from fisher_vectors.compute_sstats import read_descriptors_from_video

from fisher_vectors.constants import MAX_WIDTH
from fisher_vectors.utils.video import rescale


def compute_statistics_worker(dataset, samples, labels, sstats_out,
                              descs_to_sstats, pca, gmm, **kwargs):
    """ Computes the Fisher vectors for each slice that results from the
    temporal spliting of get_time_intervals. The resulting Fisher vectors
    are outputed to a binary file.

    """
    nr_frames_to_skip = kwargs.get('nr_frames_to_skip', 0)
    delta = kwargs.get('delta', 120)
    spacing = kwargs.get('spacing', 1)
    rescale_videos = kwargs.get('rescale_videos', 'none')
    per_shot = kwargs.get('per_shot', False)
    sample_limits_file = kwargs.get('sample_limits', None)

    if sample_limits_file:
        with open(sample_limits_file, 'r') as ff:
            sample_limits = cPickle.load(ff)
    else:
        sample_limits = None

    _, track_len, _ = parse_ip_type(dataset.FTYPE)
    track_len = (nr_frames_to_skip + 1) * int(track_len)

    D = gmm.d
    K = dataset.VOC_SIZE

    for sample, label in izip(samples, labels):
        # Still not very nice. Maybe I should create the file on the else
        # branch.
        if sstats_out.exists(str(sample)):
            continue
        sstats_out.touch(str(sample))

        # The path to the movie.
        infile = os.path.join(
            dataset.SRC_DIR,
            sample.movie + dataset.SRC_EXT)

        status = None
        if rescale_videos != 'none':
            # Rescale movie.
            status, infile = rescale(infile, MAX_WIDTH[rescale_videos],
                                     thresh=50)
            if status == 'bad_encoding':
                print 'Bad encoding ' + sample.movie
                continue

        if per_shot:
            begin_frames, end_frames = dataset.get_shots(sample.movie)
        elif sample_limits:
            begin_frames = sample_limits[sample]['begin_frames']
            end_frames = sample_limits[sample]['end_frames']
        else:
            begin_frames, end_frames = get_time_intervals(
                sample.bf, sample.ef, delta, spacing)

        # Count the number of descriptors for each chunk.
        nr_slices = len(begin_frames)
        N = np.zeros(nr_slices)
        sstats = np.zeros((nr_slices, K + 2 * K * D),
                          dtype=np.float32)

        for chunk in read_descriptors_from_video(
            infile, nr_descriptors=1, begin_frames=begin_frames,
            end_frames=end_frames, nr_skip_frames=nr_frames_to_skip):
            xx = pca.transform(chunk[:, 3:])

            # Determine slice number based on time.
            ii = get_slice_number(
                # Get time stamp of the beginning of the track.
                chunk[:, 2] - track_len + 1, begin_frames, end_frames)
            N[ii] += 1

            # Update corresponding sstats cell.
            sstats[ii] += descs_to_sstats(xx, gmm)

        # Ignore chunks with 0 descriptors
        N_not_null = N[N != 0]
        sstats = sstats[N != 0, :]
        sstats /= N_not_null[:, np.newaxis]
        # Write also the label, the number of descriptors and begin and end
        # frames.
        sstats_out.write(str(sample), sstats, info={
            'label': label,
            'nr_descs': N,
            'begin_frames': begin_frames,
            'end_frames': end_frames})

        if status == 'rescaled':
            os.remove(infile)
