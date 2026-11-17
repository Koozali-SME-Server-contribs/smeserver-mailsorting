#----------------------------------------------------------------------
#  mailsorting.pm
#  support@dungog.net
#----------------------------------------------------------------------

package esmith::FormMagick::Panel::mailsort;

use strict;
use warnings;

use esmith::util;
use esmith::FormMagick;
use esmith::AccountsDB;
use esmith::ConfigDB;
#use Unicode::IMAPUtf7;
#use Unicode::String qw(utf8 latin1);
use Encode qw(decode);

use Exporter;
use Carp qw(verbose);

use HTML::Tabulate;

our @ISA = qw(esmith::FormMagick Exporter);

our @EXPORT = qw();

our $db  = esmith::ConfigDB->open();
our $adb = esmith::AccountsDB->open();
our $pdb = esmith::ConfigDB->open('processmail') or die "Could not open processmail DB\n";

our $PanelUser = $ENV{'REMOTE_USER'} ||'';
$PanelUser = $1 if ($PanelUser =~ /^([a-z][\.\-a-z0-9]*)$/);

sub get_panel_user
{
    return $PanelUser;
}

sub get_full_name
{
    return  $adb->get_prop($PanelUser, "FirstName") . " " .
            $adb->get_prop($PanelUser, "LastName");
}

sub new {
    shift;
    my $self = esmith::FormMagick->new();
    $self->{calling_package} = (caller)[0];
    bless $self;
    return $self;
}

sub print_rules_table
{
    my $self = shift;
    my $q = $self->{cgi};

    my @rules = $pdb->get_all_by_prop(type => "$PanelUser");
    return $self->localise("NO_RULES") if (@rules == 0);

    my $rules_table =
    {
       title => $self->localise("CURRENT_RULES"),

       stripe => "#D4D0C8",

       fields => [ qw(b1 criterion b2 criterion2 action deliver copy deliver2 Modify Remove) ],

       labels => 1,

       field_attr => {
                       b1            => {  label => $self->localise("BASIS")         },

                       criterion     => {  label => $self->localise("CRITERION")     },

                       b2            => {  label => $self->localise("2ND_BASIS")     },

                       criterion2    => {  label => $self->localise("2ND_CRITERION") },

                       action       => {  label => $self->localise("ACTION")   },
                       deliver       => {  label => $self->localise("DESTINATION")   },

                       copy          => {  label => $self->localise("COPY")          },

                       deliver2      => {  label => $self->localise("DESTINATION")       },

                       Modify        => {
                                          label => $self->localise("MODIFY"),
                                          link  => \&modify_link
                                        },

                       Remove        => {
                                          label => $self->localise("REMOVE"),
                                          link  => \&remove_link
                                        },
                      }
    };

    my @data = ();
    my $a    = $self->localise('ACTION');
    my $b    = $self->localise('BASIS');
    my $c    = $self->localise('CRITERION');

    foreach my $rule (@rules)
    {
        my $key        = $rule->key;
        my $basis      = $rule->prop("basis")     || '';
        my $basis2     = $rule->prop("basis2")    || '';
        my $deliver    = $rule->prop("deliver")   || '';
        my $deliver2   = $rule->prop("deliver2")  || '';
        my $action     = $rule->prop("action")    || '';
        my $action2    = $rule->prop("action2")   || '';
        my $folder    = ("$action" eq "sort" )? $deliver  : '';
	$folder = "INBOX" if "$folder" eq "" && "$action" eq "sort";
        my $copy       = $rule->prop("copy")      || '';
        my $oldpmRule  = '';

        for ($basis, $basis2)
        {
         if ($_ eq '<')
         { $_ =  'sizelt'; }
         elsif ($_ eq '>')
         { $_ =  'sizegt'; }
        }

        my $b1    = $self->localise($basis);
        my $b2    = $self->localise($basis2);
        
        my $copyto     = $rule->prop("deliver2")  || '';# useless
        if (($copy eq 'yes') && ($action2 eq 'inbox'))
        { $deliver2 = "";  $copyto = 'inbox'; } # copyto is useless

        $deliver = GetDisplayName($deliver);
        $deliver2 = GetDisplayName($deliver2);
	
        push @data,
            {
              key        => $rule->key,
              basis      => $basis,
              basis2     => $basis2,
              criterion  => $rule->prop("criterion")  || '',
              criterion2 => $rule->prop("criterion2") || '',
              deliver    => $deliver,
              deliver2   => $deliver2,
              folder    => $folder,
              action     => $action,
              action2    => $action2,
              copy       => $copy,
              Modify     => $self->localise('MODIFY'),
              Remove     => $self->localise('REMOVE'),
              b1         => $b1,
              b2         => $b2,
              a          => $a,
              b          => $b,
              c          => $c,
            }
    }

    my $t = HTML::Tabulate->new($rules_table);

    $t->render(\@data, $rules_table);
}

sub modify_or_create_description
{
    my $self = shift;
    my $q = $self->{cgi};

    my $key = $q->param('key');

    if ($key eq 'new')
    { return $self->localise('CREATE_RULE_DESCRIPTION'); }
    else
    { return $self->localise('MODIFY_RULE_DESCRIPTION'); }
}

sub priority
{
    my $self = shift;
    my $q = $self->{cgi};

    my $key = $q->param('key');

    if ($key eq 'new')
    { return ''; }
    else
    {
      my $start = ' <tr>
                     <td class="sme-noborders-label">' . $self->localise('PRIORITY') . '
                     <td class="sme-noborders-content"><INPUT VALUE="' . $key . '" NAME="key" TYPE="text" SIZE="40"></td>
                    </tr> ';
      return $start;
    }
}

sub filter_status
{
    my $self = shift;
    my $q = $self->{cgi};

    my $FilterType = $db->get_prop('postfix', "FilterType") || 'Disabled';

    if ($FilterType eq 'Disabled')
    {
      my $start = '<tr><td colspan="2"><p>' . 
                      $self->localise('FILTERTYPE_DISABLED') . 
                   '</p></td></tr> ';
    }
    else
    { return ''; }
}

sub user_status
{
    my $self = shift;
    my $q = $self->{cgi};

    my $MailFilter = $adb->get_prop($PanelUser, "MailFilter") || '';

    if ($MailFilter eq 'bypass')
    {
      my $start = '<tr><td colspan="2"><p>' .
                      $self->localise('USER_DISABLED') .
                  ' </p></td></tr> ';
    }
    else
    { return ''; }
}

sub modify_link  
{
    my ($data_item, $row, $field) = @_;

    #avoid duplicate data if we sort we use folder field
    my $deliver = $row->{deliver};
    $deliver="" if $row->{action} eq "sort";

    return "userpanel-mailsort?" .
        join("&",
        "page=0",
        "page_stack=",
        "Next=Next",
        "key="        . $row->{key},
        "oldkey="     . $row->{key},
        "basis="      . $row->{basis},
        "basis2="     . $row->{basis2},
        "criterion="  . $row->{criterion},
        "criterion2=" . $row->{criterion2},
        "deliver="    . $deliver,
        "deliver2="   . $row->{deliver2},
        "folder="    . $row->{folder},
        "action="     . $row->{action},
        "action2="    . $row->{action2},
        "copy="       . $row->{copy},
        "wherenext=RULE_MODIFY");
}

sub remove_link
{
    my ($data_item, $row, $field) = @_;

    return "userpanel-mailsort?" .
        join("&",
        "page=0",
        "page_stack=",
        "Next=Next",
        "key="      . $row->{key},
        "desc="     . $row->{b} .' = '. $row->{basis}     . '<br>' .
                      $row->{c} .' = '. $row->{criterion} . '<br>' .
                      $row->{a} .' = '. $row->{action},
        "wherenext=RULE_REMOVE");
}

sub remove_rule
{
    my $self = shift;
    my $q = $self->{cgi};

    my $rule = $q->param('key');

    my $rec = $pdb->get($rule);
    $rec->delete;

    unless ( system ("/sbin/e-smith/signal-event mailsorting-conf $PanelUser") == 0 )
    { return $self->error('ERROR_UPDATING'); }

    return $self->success("SUCCESS");
}

sub save_rule
{
    my $self = shift;
    my $q = $self->{cgi};

    my $rule = $q->param ('key')  || '';
    if (($rule eq '') || ($rule eq 'new'))
    {
      my $random = int(rand(999999));
      $rule = $PanelUser.$random;
      $pdb->new_record($rule, { type => "$PanelUser" });
    }
    my %filtered;
    $filtered{criterion}      .= $q->param ('criterion')     || '';
    $filtered{criterion2}    .= $q->param ('criterion2')    || '';
    $filtered{basis}      .= $q->param ('basis')     || '';
    $filtered{basis2}    .= $q->param ('basis2')    || '';
    $filtered{action}    .= $q->param ('action')     || '';
    $filtered{action2}   .= $q->param ('action2')    || '';
    $filtered{deliver}   .= $q->param ('deliver')    || '';
    $filtered{deliver2}   .= $q->param ('deliver2')   || '';
    $filtered{folder}    .= $q->param ('folder')    || '';
    $filtered{copy}       .= $q->param ('copy')       || '';
    $filtered{oldkey}     .= $q->param ('oldkey')     || '';

    if ($filtered{basis} eq 'sizelt')  { $filtered{basis}  = '<'; }
    if ($filtered{basis} eq 'sizegt')  { $filtered{basis}  = '>'; }
    if ($filtered{basis2} eq 'sizelt') { $filtered{basis2} = '<'; }
    if ($filtered{basis2} eq 'sizegt') { $filtered{basis2} = '>'; }

    # we use the folder drop box selection if asked to sort
    $filtered{folder} = "" if $filtered{folder} eq "INBOX";
    $filtered{deliver} = $filtered{folder} if $filtered{action} eq "sort";

    if ($filtered{copy} eq 'no')       { $filtered{deliver2} = '';  $filtered{action2} = ''; }
    if ($filtered{copy} eq 'yes' &&  $filtered{action2} eq 'inbox')       { $filtered{deliver2} = ''; }

    # keys are different but rule at least has part of users name so is likely changed
    if (($filtered{oldkey} ne $rule) && ($filtered{oldkey} =~ /$PanelUser/))
    {
        $pdb->new_record($rule, { type => "$PanelUser" });

        my $rec = $pdb->get($filtered{oldkey});
        $rec->delete;
    }

    foreach ("criterion","criterion2","action","action2","copy","basis","basis2","deliver","deliver2" )
    { $pdb->set_prop($rule, "$_", $filtered{$_}); }

    unless ( system ("/sbin/e-smith/signal-event mailsorting-conf $PanelUser") == 0 )
    { return $self->error('ERROR_UPDATING'); }

    return $self->success("SUCCESS");
}

#sub GetDisplayName ($)
#{
	#my $s = shift;
	#my $t = Unicode::IMAPUtf7->new();
	#$s =~ s/(.*)//; # untaint it
	#my $u = utf8($t->decode($1));
	#return $u->utf8;#$u->latin1;
#}

sub GetDisplayName {
    my ($s) = @_;
    $s =~ s/(.*)//;   # untaint the input
    my $decoded = decode('IMAP-UTF-7', $1);
    return $decoded;
}


sub listfolders
{
	use File::Find::Rule;
	my $root="/home/e-smith/files/users/$PanelUser/Maildir";
	$root="/home/e-smith/Maildir"  if  "$PanelUser" eq "admin" ;
	my @dirs = File::Find::Rule->new
	    ->extras({ untaint => 1 , untaint_pattern => qr|^([-+@\w&. /]+)$| })
	    ->directory
	    ->maxdepth(1)
	    ->in($root);
	my %out_dir;
	$out_dir{"INBOX"} .= "INBOX";
	$out_dir{""} .= "";
	for (sort @dirs) {
	       s/$root\/?\.?//;
	       my @exclu =("cur", "tmp", "new" , "INBOX" );
	       next if $_  ~~ @exclu;
	       $out_dir{$_} .= GetDisplayName(join('/',split('\.', $_)));
       	}
	return \%out_dir;
}

sub nonblankWithForward
{
    my $self = shift;
    my $q = $self->{cgi};

    my $action   = $q->param ('action')  || '';
    my $deliver  = $q->param ('deliver') || '';

    if ( $action eq 'sort')
    {
	return "ERROR_SHOULD_BE_EMPTY" unless not $deliver;
	return "OK";
    }
    elsif ( $action ne 'delete')
    {
      if (not $deliver)
      { return "ERROR_FORWARD_NO_EMAIL"; }
      elsif (  $deliver =~ /^\s+$/ )
      { return "ERROR_FORWARD_NO_EMAIL"; }
      else
      { return "OK"; }
    }
    else { return "OK"; }
}

sub nonblankWithForward2
{
    my $self = shift;
    my $q = $self->{cgi};

    my $copy     = $q->param ('copy')     || '';
    my $action   = $q->param ('action2')  || '';
    my $deliver  = $q->param ('deliver2') || '';

    if (( $action eq 'forward') && ( $copy eq 'yes'))
    {
      if (not $deliver)
      { return "ERROR_FORWARD_NO_EMAIL"; }
      elsif (  $deliver =~ /^\s+$/ )
      { return "ERROR_FORWARD_NO_EMAIL"; }
      else
      { return "OK"; }
    }
    else { return "OK"; }
}

sub nonblankWithSort
{
    my $self = shift;
    my $q = $self->{cgi};

    my $action   = $q->param ('action')  || '';
    my $folder  = $q->param ('folder') || '';

    if ( $action eq 'sort')
    {
        return "ERROR_SORT_NO_FOLDER" if not $folder;
        return "OK";
    }
    else { return "OK"; }
}


1;
