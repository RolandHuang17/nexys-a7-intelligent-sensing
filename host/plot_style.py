"""Shared visual style for existing board-data plots; no data transforms."""
def apply(plt):
    from cycler import cycler
    plt.rcParams.update({
        'font.family':'Microsoft YaHei','font.size':10,'axes.unicode_minus':False,
        'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False,
        'axes.facecolor':'#F5F8FB','figure.facecolor':'white','savefig.facecolor':'white',
        'text.color':'#243E52','axes.labelcolor':'#243E52','axes.edgecolor':'#BAC7D3',
        'xtick.color':'#60758A','ytick.color':'#60758A','grid.color':'#BAC7D3',
        'axes.titleweight':'bold','axes.titlelocation':'left','axes.titlepad':10,
        'axes.labelpad':8,'legend.facecolor':'white','legend.edgecolor':'none',
        'axes.prop_cycle':cycler(color=['#2868AA','#168C82','#B47720','#BC5356']),
    })

def finish(fig):
    for i,ax in enumerate(fig.axes):
        ax.tick_params(length=3,width=.65)
        ax.text(.985,.94,f'{chr(97+i)})',transform=ax.transAxes,ha='right',va='top',
                color='#60758A',fontsize=9,fontweight='bold')
