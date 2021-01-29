
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt
from scipy import stats
import os
from skimage import img_as_ubyte

def reshape_to_rgb(grey_img):
    # makes single color channel image into rgb
    ret_img = np.zeros(shape=[grey_img.shape[0], grey_img.shape[1], 3], dtype='uint8')
    grey_img_ = img_as_ubyte(grey_img)

    ret_img[:, :, 0] = grey_img_
    ret_img[:, :, 1] = grey_img_
    ret_img[:, :, 2] = grey_img_
    return ret_img

class msd_diffusion:

    def __init__(self):
        self.tracks = np.asarray([])
        self.msd_tracks = np.asarray([])
        self.D_linfits = np.asarray([])
        self.track_lengths = np.asarray([])
        self.track_step_sizes=np.asarray([])
        self.save_dir = '.'

        self.time_step = 0.010 #time between frames, in seconds
        self.micron_per_px = 0.11
        self.min_track_len_linfit=11
        self.min_track_len_step_size = 3
        self.max_tlag_step_size=3
        self.track_len_cutoff_linfit=11
        self.perc_tlag_linfit=25
        self.use_perc_tlag_linfit=False
        self.initial_guess_linfit=0.2

        self.tracks_num_cols=4
        self.tracks_id_col=0
        self.tracks_frame_col=1
        self.tracks_x_col=2
        self.tracks_y_col=3
        self.tracks_step_size_col=4

        self.msd_num_cols=8
        self.msd_id_col = 0
        self.msd_t_col = 1
        self.msd_frame_col = 2
        self.msd_x_col = 3
        self.msd_y_col = 4
        self.msd_msd_col = 5
        self.msd_std_col = 6
        self.msd_len_col = 7

        self.D_lin_num_cols=7
        self.D_lin_id_col = 0
        self.D_lin_D_col = 1
        self.D_lin_err_col = 2
        self.D_lin_rsq_col = 3
        self.D_lin_rmse_col = 4
        self.D_lin_len_col = 5
        self.D_lin_Dlen_col = 6

    def set_track_data(self, track_data):
        self.tracks=track_data
        self.msd_tracks = np.asarray([])
        self.D_linfits = np.asarray([])
        self.fill_track_lengths()
        self.fill_track_sizes()

    def msd2d(self, x, y):
        shifts = np.arange(1, len(x), 1)
        MSD = np.zeros(shifts.size)
        MSD_std = np.zeros(shifts.size)

        for i, shift in enumerate(shifts):
            sum_diffs_sq = np.square(x[shift:] - x[:-shift]) + np.square(y[shift:] - y[:-shift])
            MSD[i] = np.mean(sum_diffs_sq)
            MSD_std[i] = np.std(sum_diffs_sq)

        return MSD, MSD_std

    def fill_track_lengths(self):
        # fill track length array with the track lengths
        ids = np.unique(self.tracks[:, self.tracks_id_col])
        self.track_lengths = np.zeros((len(ids), 2))
        for i,id in enumerate(ids):
            cur_track = self.tracks[np.where(self.tracks[:, self.tracks_id_col] == id)]
            self.track_lengths[i,0] = id
            self.track_lengths[i,1] = len(cur_track)

    def fill_track_sizes(self):
        # add column to tracks array containing the step size for each step of each track (distance between points)
        self.tracks = np.append(self.tracks, np.zeros((len(self.tracks),1)), axis=1)
        ids = np.unique(self.tracks[:, self.tracks_id_col])
        ss_i=0
        for i,id in enumerate(ids):
            cur_track = self.tracks[np.where(self.tracks[:, self.tracks_id_col] == id)]
            ss_i+=1
            for j in range(1,len(cur_track),1):
                d = np.sqrt((cur_track[j, self.tracks_x_col] - cur_track[j-1, self.tracks_x_col]) ** 2 +
                        (cur_track[j, self.tracks_y_col] - cur_track[j-1, self.tracks_y_col]) ** 2)
                self.tracks[ss_i,self.tracks_step_size_col] = d
                ss_i+=1

    def step_sizes_and_angles(self):
        # calculates step sizes and angles for tracks with min. length that is given for Linear fit
        ids = self.track_lengths[self.track_lengths[:,1] >= self.min_track_len_step_size][:,0]
        track_lens=self.track_lengths[self.track_lengths[:,1] >= self.min_track_len_step_size][:,1]

        #rows correspond to t-lag==1,2,3,4,5, columns list the step sizes
        tlag1_dim_steps = int(np.sum(track_lens - 1))
        self.step_sizes = np.empty((self.max_tlag_step_size, tlag1_dim_steps,))
        self.step_sizes.fill(np.nan)

        tlag1_dim_angles = int(np.sum(track_lens - 2))
        self.angles = np.empty((self.max_tlag_step_size, tlag1_dim_angles,))
        self.angles.fill(np.nan)

        #used for angle autocorrelation
        #self.angles_tlag1 = np.empty((len(ids),max_track_len-2))
        #self.angles_tlag1.fill(np.nan)

        start_arr=np.zeros((self.max_tlag_step_size,), dtype='int')
        angle_start_arr = np.zeros((self.max_tlag_step_size,), dtype='int')
        for id_i,id in enumerate(ids):
            cur_track = self.tracks[np.where(self.tracks[:, self.tracks_id_col] == id)]
            num_shifts = min(self.max_tlag_step_size,len(cur_track)-1)
            max_num_angle_tlags= int((len(cur_track) - 1) / 2)
            x = cur_track[:, self.tracks_x_col]
            y = cur_track[:, self.tracks_y_col]
            shifts = np.arange(1, num_shifts+1, 1)
            for i, shift in enumerate(shifts):
                x_shifts = x[shift:] - x[:-shift]
                y_shifts = y[shift:] - y[:-shift]
                if(False): #i < max_num_angle_tlags):
                    # relative angle: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3856831/
                    vecs = np.column_stack((x_shifts, y_shifts))
                    theta=np.zeros(len(vecs)-1-i)
                    for vec_i in range(len(vecs)-1-i):
                        if(np.linalg.norm(vecs[vec_i]) == 0 or np.linalg.norm(vecs[vec_i+1+i]) == 0):
                            print("norm of vec is 0: id=", id)
                        theta[vec_i] = np.rad2deg(np.arccos(np.dot(vecs[vec_i],vecs[vec_i+1+i]) / (np.linalg.norm(vecs[vec_i]) * np.linalg.norm(vecs[vec_i+1+i]))))
                    self.angles[i][angle_start_arr[i]:angle_start_arr[i]+len(theta)] = theta
                    #if(i==0):
                    #   self.angles_tlag1[id_i][:len(theta)]=theta
                    angle_start_arr[i] += len(theta)

                sum_diffs_sq = np.square(x[shift:] - x[:-shift]) + np.square(y[shift:] - y[:-shift])
                self.step_sizes[i][start_arr[i]:start_arr[i]+len(sum_diffs_sq)] = np.sqrt(sum_diffs_sq)*self.micron_per_px
                start_arr[i] += len(sum_diffs_sq)

    def msd_all_tracks(self):
        # for each track, do MSD calculation
        ids = np.unique(self.tracks[:,self.tracks_id_col])
        self.msd_tracks = np.zeros((len(self.tracks),self.msd_num_cols), )
        i=0
        for id in ids:
            cur_track = self.tracks[np.where(self.tracks[:,self.tracks_id_col]==id)]
            n_MSD=len(cur_track)
            cur_MSD, cur_MSD_std = self.msd2d(cur_track[:, self.tracks_x_col] * self.micron_per_px,
                                                              cur_track[:, self.tracks_y_col] * self.micron_per_px)
            self.msd_tracks[i:i+n_MSD,self.msd_id_col] = id
            self.msd_tracks[i:i+n_MSD,self.msd_t_col] = np.arange(0,n_MSD,1)*self.time_step
            self.msd_tracks[i:i + n_MSD, self.msd_frame_col] = cur_track[:, self.tracks_frame_col]
            self.msd_tracks[i:i + n_MSD, self.msd_x_col] = cur_track[:, self.tracks_x_col]
            self.msd_tracks[i:i + n_MSD, self.msd_y_col] = cur_track[:, self.tracks_y_col]
            self.msd_tracks[i+1:i+n_MSD,self.msd_msd_col] = cur_MSD
            self.msd_tracks[i+1:i+n_MSD,self.msd_std_col] = cur_MSD_std
            self.msd_tracks[i:i+n_MSD,self.msd_len_col] = n_MSD-1
            i += n_MSD

    def fit_msd(self, type="brownian"):
        # fit MSD curve to get Diffusion coefficient
        # filter for tracks > min-length

        if(len(self.msd_tracks) == 0):
            return ()

        if (type == 'brownian'):
            #msd_len is one less than the track len
            valid_tracks = self.msd_tracks[np.where(self.msd_tracks[:, self.msd_len_col] >= (self.min_track_len_linfit-1))]

            ids = np.unique(valid_tracks[:,self.msd_id_col])
            self.D_linfits = np.zeros((len(ids),self.D_lin_num_cols,))
            for i,id in enumerate(ids):
                cur_track = valid_tracks[np.where(valid_tracks[:, self.msd_id_col] == id)]
                if(self.use_perc_tlag_linfit):
                    stop = int(cur_track[0][self.msd_len_col] * (self.perc_tlag_linfit/100))+1
                else:
                    stop = self.track_len_cutoff_linfit

                def linear_fn(x, a):
                    return 4 * a * x
                linear_fn_v = np.vectorize(linear_fn)

                ##### Correct way
                popt, pcov = curve_fit(linear_fn, cur_track[1:stop,self.msd_t_col], cur_track[1:stop,self.msd_msd_col],
                                       p0=[self.initial_guess_linfit,])
                residuals = cur_track[1:stop,self.msd_msd_col] - linear_fn_v(cur_track[1:stop,self.msd_t_col], popt[0])
                ss_res = np.sum(residuals ** 2)
                rmse = np.mean(residuals**2)**0.5
                ss_tot = np.sum((cur_track[1:stop,self.msd_msd_col] - np.mean(cur_track[1:stop,self.msd_msd_col])) ** 2)
                #####

                ##### Matches matlab script results
                # popt, pcov = curve_fit(linear_fn, cur_track[0:stop-1, self.msd_t_col],cur_track[1:stop, self.msd_msd_col],
                #                        p0=[self.initial_guess_linfit, ])
                # residuals = cur_track[1:stop, self.msd_msd_col] - linear_fn_v(cur_track[0:stop-1, self.msd_t_col],popt[0])
                # ss_res = np.sum(residuals ** 2)
                # rmse = np.mean(residuals ** 2) ** 0.5
                # ss_tot = np.sum((cur_track[1:stop, self.msd_msd_col] - np.mean(cur_track[1:stop, self.msd_msd_col])) ** 2)
                #####

                r_squared = 1 - (ss_res / ss_tot)

                D = popt[0]
                perr=np.sqrt(np.diag(pcov))

                self.D_linfits[i][self.D_lin_id_col]=id
                self.D_linfits[i][self.D_lin_D_col]=D
                self.D_linfits[i][self.D_lin_err_col]=perr
                self.D_linfits[i][self.D_lin_rsq_col] = r_squared
                self.D_linfits[i][self.D_lin_rmse_col] = rmse
                self.D_linfits[i][self.D_lin_len_col] = cur_track[0][self.msd_len_col]
                self.D_linfits[i][self.D_lin_Dlen_col] = stop-1
        else:
            # no other type supported currently
            print("Error: fit_msd: unknown type of fit.")

    def save_fit_data(self, file_name="fit_results.txt"):
        df = pd.DataFrame(self.D_linfits)
        df.rename(columns={self.D_lin_id_col: 'id', self.D_lin_D_col: 'D', self.D_lin_err_col: 'err',
                           self.D_lin_rsq_col: 'r_sq', self.D_lin_rmse_col: 'rmse', self.D_lin_len_col: 'track_len',
                           self.D_lin_Dlen_col: 'D_track_len'}, inplace=True)
        df.to_csv(self.save_dir + '/' + file_name, sep='\t', index=False)
        return df

    def save_msd_data(self, file_name="msd_results.txt"):
        df = pd.DataFrame(self.msd_tracks)
        df.rename(columns={self.msd_id_col: 'id', self.msd_t_col: 't', self.msd_frame_col: 'frame',
                           self.msd_x_col: 'x', self.msd_y_col: 'y', self.msd_msd_col: 'MSD',
                           self.msd_std_col: 'MSD_stdev', self.msd_len_col: 'MSD_len'}, inplace=True)
        df.to_csv(self.save_dir + '/' + file_name, sep='\t', index=False)
        return df

    def plot_msd_curves(self,file_name="msd_all.pdf", max_tracks=50, ymax=-1, rsq_cutoff=0.85):
        num_tracks_plotted = 0
        for i in range(len(self.D_linfits)):
            cur_track = self.msd_tracks[self.msd_tracks[:,self.msd_id_col]==self.D_linfits[i][self.D_lin_id_col]]
            if(self.D_linfits[i,self.D_lin_rsq_col] > rsq_cutoff):
                plt.plot(cur_track[:self.track_len_cutoff_linfit+1,self.msd_t_col], cur_track[:self.track_len_cutoff_linfit+1,self.msd_msd_col], '-', color="blue", linewidth=".5")
                num_tracks_plotted += 1
            if(num_tracks_plotted>max_tracks):
                break

        plt.xlabel('t (s)')
        plt.ylabel('MSD (microns^2)')
        if(ymax>0):
            plt.ylim(0,ymax)
        plt.savefig(self.save_dir + '/' + file_name)
        plt.clf()

    def save_step_sizes(self, file_name="step_sizes.txt"):
        df = pd.DataFrame(self.step_sizes)
        df.insert(0, 't', range(1,len(self.step_sizes)+1))
        df.to_csv(self.save_dir + '/' + file_name, sep='\t', index=False)
        return df

    def save_angles(self, file_name="relative_angles.txt"):
        df = pd.DataFrame(self.angles)
        df.insert(0, 't', range(1, len(self.angles) + 1))
        df.to_csv(self.save_dir + '/' + file_name, sep='\t', index=False)
        return df

    def save_track_length_hist(self, file_name="track_length_histogram.pdf"):
        to_plot = self.track_lengths[np.where(self.track_lengths[:,1] >= (self.track_len_cutoff_linfit-1))][:,1]
        plt.hist(to_plot, bins=np.arange(0,np.max(to_plot),1))
        plt.savefig(self.save_dir + '/' + file_name)
        plt.clf()

    def save_step_size_hist(self, file_name="step_sizes.pdf", tlag=1):

        to_plot = self.step_sizes[tlag-1,:]
        to_plot = to_plot[np.logical_not(np.isnan(to_plot))]
        plt.hist(to_plot, bins=np.arange(0,np.max(to_plot),0.1))
        plt.savefig(self.save_dir + '/' + file_name)
        plt.clf()

    def save_angle_hist(self, file_name="angles.pdf", tlag=1):
        to_plot = self.angles[tlag - 1, :]
        to_plot = to_plot[np.logical_not(np.isnan(to_plot))]

        #histogram
        plt.hist(to_plot, bins=np.arange(0, 180+5, 5))
        plt.savefig(self.save_dir + '/' + file_name)
        plt.clf()

        #KDE
        gkde = stats.gaussian_kde(to_plot)
        ind = np.arange(0, 180+0.1, 0.1)
        kdepdf = gkde.evaluate(ind)
        plt.plot(ind, kdepdf)
        ext=os.path.splitext(file_name)[1]
        plt.savefig(self.save_dir + '/' + file_name[:-(len(ext))]+"_kde"+ext)
        plt.clf()

    def save_D_histogram(self, file_name="Deff.pdf"):

        df = pd.DataFrame(self.D_linfits)
        df.rename(columns={self.D_lin_id_col: 'id', self.D_lin_D_col: 'D', self.D_lin_err_col: 'err',
                           self.D_lin_rsq_col: 'r_sq', self.D_lin_rmse_col: 'rmse', self.D_lin_len_col: 'track_len',
                           self.D_lin_Dlen_col: 'D_track_len'}, inplace=True)


        to_plot = self.D_linfits[:,self.D_lin_D_col]

        # histogram
        plt.hist(to_plot, bins=np.arange(0, 10, 0.1))
        plt.savefig(self.save_dir + '/' + file_name)
        plt.clf()

        # KDE
        gkde = stats.gaussian_kde(to_plot)
        ind = np.arange(0, 10, 0.1)
        kdepdf = gkde.evaluate(ind)
        plt.plot(ind, kdepdf)
        ext = os.path.splitext(file_name)[1]
        plt.savefig(self.save_dir + '/' + file_name[:-(len(ext))] + "_kde" + ext)
        plt.clf()

    def save_tracks_to_img_ss(self, ax):
        from matplotlib import cm

        max_ss=np.max(self.tracks[:,self.tracks_step_size_col])
        ids = np.unique(self.tracks[:, self.tracks_id_col])
        for id in ids:
            cur_track = self.tracks[self.tracks[:, self.tracks_id_col] == id]
            for step_i in range(1,len(cur_track),1):
                show_color = cur_track[step_i,self.tracks_step_size_col] / max_ss

                ax.plot([cur_track[step_i-1,self.tracks_x_col],cur_track[step_i,self.tracks_x_col]],
                        [cur_track[step_i-1,self.tracks_y_col],cur_track[step_i,self.tracks_y_col]],
                        '-', color=cm.jet(show_color), linewidth=0.4)  # 0.25)

    def save_tracks_to_img(self, ax, len_cutoff='default', max_Deff=0.5):
        from matplotlib import cm

        if(len_cutoff == 'default'):
            len_cutoff=self.track_len_cutoff_linfit

        ids=np.unique(self.tracks[:,self.tracks_id_col])
        for id in ids:
            cur_track=self.tracks[self.tracks[:,self.tracks_id_col]==id]
            if(len(cur_track) >= self.min_track_len_linfit):
                if(len_cutoff != 'none'):
                    x_vals=cur_track[0:len_cutoff,self.tracks_x_col]
                    y_vals=cur_track[0:len_cutoff,self.tracks_y_col]
                else:
                    x_vals = cur_track[:, self.tracks_x_col]
                    y_vals = cur_track[:, self.tracks_y_col]

                D = self.D_linfits[self.D_linfits[:,self.D_lin_id_col]==id][0,self.D_lin_D_col]


                show_color=D/max_Deff
                if(show_color>1):
                    print("need to raise max_D, ",D)
                    show_color=1
                ax.plot(x_vals,y_vals,'-',color=cm.jet(show_color),linewidth=0.4) #0.25)


    # def save_angle_autocorr(self, file_name="angles_autocorr.pdf"):
    #     from statsmodels.graphics.tsaplots import plot_acf
    #     from statsmodels.tsa.stattools import acf
    #
    #     mean_acf_y_vals=np.zeros(len(self.angles_tlag1[0]))
    #     for i in range(len(self.angles_tlag1)):
    #         mean_acf_y_vals += acf(self.angles_tlag1[i])
    #     mean_acf_y_vals /= len(self.angles_tlag1)
    #
    #     plt.scatter(range(0, len(mean_acf_y_vals)), mean_acf_y_vals, marker='.', color="blue")
    #     plt.bar(x=range(0,len(mean_acf_y_vals)), height=mean_acf_y_vals, width=0.05, color="black")
    #     plt.plot([-0.5,len(mean_acf_y_vals)],[0,0],color='blue')
    #     plt.xlim(-0.5,len(mean_acf_y_vals))
    #     plt.ylim(-1,1.25)
    #     plt.savefig(self.save_dir + '/' + file_name)
    #     plt.clf()
    #
    #     # plot_acf(self.angles_tlag1[0])
    #     # plt.savefig(self.save_dir + '/0_' + file_name)
    #     # plt.clf()

test1=False
test2=False
if(test1):
    dir_="/Users/sarahkeegan/Dropbox/mac_files/holtlab/data_and_results/GEMs/for_presentation"

    #file_="Traj_GBC1_3W_0min_GEM_6_cyto.tif.csv"
    #suffix = '3W_0hr'  # med(D) = 0.54
    #ym = -1

    #file_ = "Traj_GBC1_3W_5_hour_GEM_4_cyto.tif.csv"
    #suffix='3W_5hr' # med(D) = 0.04
    #ym = -1

    file_="GBC1_4_cyto.csv"
    suffix = 'CTRL' # med(D) = 0.18
    ym = 0.4

    track_data_df = pd.read_csv(dir_ + '/' + file_)
    track_data_df = track_data_df[['Trajectory', 'Frame', 'x', 'y']]
    track_data = track_data_df.to_numpy()

    msd_diff = msd_diffusion()
    msd_diff.set_track_data(track_data)
    msd_diff.step_sizes_and_angles()

    msd_diff.msd_all_tracks()
    msd_diff.fit_msd()

    msd_diff.save_dir = dir_ + '/results_'+suffix

    msd_diff.save_angles()
    msd_diff.save_step_sizes()

    msd_diff.save_msd_data()
    df=msd_diff.save_fit_data()
    print(np.median(df['D']))
    msd_diff.save_track_length_hist()
    msd_diff.save_step_size_hist("step_sizes1.pdf",1)


    msd_diff.save_step_size_hist("step_sizes2.pdf", 2)
    msd_diff.save_step_size_hist("step_sizes3.pdf", 3)
    # msd_diff.save_step_size_hist("step_sizes4.pdf", 4)
    # msd_diff.save_step_size_hist("step_sizes5.pdf", 5)

    #msd_diff.save_angle_hist("angles1.pdf", 1)
    #msd_diff.save_angle_hist("angles2.pdf", 2)
    #msd_diff.save_angle_hist("angles3.pdf", 3)

    #msd_diff.save_angle_hist("angles4.pdf", 4)
    #msd_diff.save_angle_hist("angles5.pdf", 5)

    msd_diff.plot_msd_curves(ymax=ym, max_tracks=30)

    msd_diff.save_D_histogram("Deff.pdf")

if(test2):
    dir_="/Users/sarahkeegan/Dropbox/mac_files/holtlab/data_and_results/tamas-20201218_HeLa_hPNE_nucPfV_NPM1_clones/tracks/"
    file_name='Traj_02_WT_hPNE_nucPfV_010_01.csv'

    track_data_df = pd.read_csv(dir_ + '/' + file_name)
    track_data_df = track_data_df[['Trajectory', 'Frame', 'x', 'y']]
    track_data = track_data_df.to_numpy()

    msd_diff = msd_diffusion()
    msd_diff.micron_per_px=0.1527
    msd_diff.time_step=0.010
    msd_diff.set_track_data(track_data)

    msd_diff.msd_all_tracks()
    msd_diff.fit_msd()

    msd_diff.save_dir = dir_ + '/results'

    msd_diff.save_msd_data()
    df = msd_diff.save_fit_data()
    print(np.median(df['D']))











