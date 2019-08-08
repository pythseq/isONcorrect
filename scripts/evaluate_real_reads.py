
from __future__ import print_function
import os,sys
import argparse
import re
import errno
import itertools

import parasail
import pysam

'''
    Below code taken from https://github.com/lh3/readfq/blob/master/readfq.py
'''
def readfq(fp): # this is a generator function
    last = None # this is a buffer keeping the last unprocessed line
    while True: # mimic closure; is it a bad idea?
        if not last: # the first record or a record following a fastq
            for l in fp: # search for the start of the next record
                if l[0] in '>@': # fasta/q header line
                    last = l[:-1] # save this line
                    break
        if not last: break
        name, seqs, last = last[1:].replace(" ", "_"), [], None
        for l in fp: # read the sequence
            if l[0] in '@+>':
                last = l[:-1]
                break
            seqs.append(l[:-1])
        if not last or last[0] != '+': # this is a fasta record
            yield name, (''.join(seqs), None) # yield a fasta record
            if not last: break
        else: # this is a fastq record
            seq, leng, seqs = ''.join(seqs), 0, []
            for l in fp: # read the quality
                seqs.append(l[:-1])
                leng += len(l) - 1
                if leng >= len(seq): # have read enough quality
                    last = None
                    yield name, (seq, ''.join(seqs)); # yield a fastq record
                    break
            if last: # reach EOF before reading enough quality
                yield name, (seq, None) # yield a fasta record instead
                break



def cigar_to_seq_mm2(read, full_r_seq, full_q_seq):
    # print()
    r_index = 0
    q_index = 0
    r_seq = full_r_seq[read.reference_start: read.reference_end + 1]
    q_seq = full_q_seq[read.query_alignment_start: read.query_alignment_end + 1]
    r_line, m_line, q_line = [], [], []

    cigar_tuples = read.cigartuples
    # print(cigar_tuples)
    # print(full_r_seq)
    # print(full_q_seq)

    # if query is softclipped in beginning or ref seq starts earlier
    if read.query_alignment_start > 0 or read.reference_start > 0:
        r_line.append( "-"*max(0, read.query_alignment_start - read.reference_start ) + full_r_seq[ : read.reference_start ] )
        q_line.append( "-"*max(0, read.reference_start - read.query_alignment_start ) + full_q_seq[ : read.query_alignment_start ]  ) 
        m_line.append("X"*max(read.query_alignment_start, read.reference_start ) )
        if cigar_tuples[0][0] in set([2,3,4]) and read.query_alignment_start == cigar_tuples[0][1]:
            del cigar_tuples[0]

    # if query is softclipped in end or ref seq extends beyond alignment 
    ref_end_offset = len(full_r_seq) - read.reference_end
    q_end_offset = len(full_q_seq) - read.query_alignment_end

    if q_end_offset > 0 or ref_end_offset > 0:
        # print(q_end_offset, ref_end_offset, "lol")
        if ref_end_offset:
            r_end = full_r_seq[ -ref_end_offset : ] + "-"*max(0, q_end_offset - ref_end_offset ) 
        else:
            r_end =  "-" * q_end_offset 

        if q_end_offset:
            q_end = full_q_seq[ -q_end_offset : ] + "-"*max(0, ref_end_offset - q_end_offset ) 
        else:
            q_end = "-" * ref_end_offset 

        m_end = "X"*max(q_end_offset, ref_end_offset )

        if cigar_tuples[-1][0] in set([2,3,4]) and q_end_offset == cigar_tuples[-1][1]:
            # print("HAHAHAHAHAHA")
            del cigar_tuples[-1]
        # del cigar_tuples[-1]
        # print(r_end, m_end, q_end)
    else:
        r_end, m_end, q_end = "", "", ""
    # print(cigar_tuples)

    for (op_type, op_len) in cigar_tuples:
        # op_len = int(op_len)
        if op_type == 0:
            ref_piece = r_seq[r_index: r_index + op_len]
            query_peace = q_seq[q_index: q_index + op_len]
            # print(ref_piece)
            # print(query_peace)

            r_line.append(ref_piece)
            q_line.append(query_peace)
            match_seq = ''.join(['|' if r_base.upper() == q_base.upper() else '*' for (r_base, q_base) in zip(ref_piece, query_peace)]) # faster with "".join([list of str]) instead of +=
                
            m_line.append(match_seq)
            r_index += op_len
            q_index += op_len

        elif op_type == 1:
            # insertion into reference
            r_line.append('-' * op_len)
            m_line.append(' ' * op_len)
            q_line.append(q_seq[q_index: q_index + op_len])
            #  only query index change
            q_index += op_len
        elif op_type == 2 or op_type == 3 or op_type == 4:
            # deletion from reference
            r_line.append(r_seq[r_index: r_index + op_len])
            m_line.append(' ' * op_len)
            q_line.append('-' * op_len)
            #  only ref index change
            r_index += op_len
            # print("here", r_index)

    r_line.append(r_end)
    m_line.append(m_end)
    q_line.append(q_end)    

    return "".join([s for s in r_line]), "".join([s for s in m_line]), "".join([s for s in q_line])

def cigar_to_seq_mm2_local(read, full_r_seq, full_q_seq):

    """
        Changed to parsing = and X instead of simple M.
    """
    # print()
    r_index = 0
    q_index = 0
    r_seq = full_r_seq[read.reference_start: read.reference_end + 1]
    q_seq = full_q_seq[read.query_alignment_start: read.query_alignment_end + 1]
    r_line, m_line, q_line = [], [], []

    cigar_tuples = read.cigartuples
    r_end, m_end, q_end = "", "", ""
    ins, del_, subs, matches = 0, 0, 0, 0
    # print(cigar_tuples)
    for (op_type, op_len) in cigar_tuples:
        # print((op_type, op_len))
        # op_len = int(op_len)
        if op_type == 7:
            ref_piece = r_seq[r_index: r_index + op_len]
            query_peace = q_seq[q_index: q_index + op_len]
            # print(ref_piece)
            # print(query_peace)

            r_line.append(ref_piece)
            q_line.append(query_peace)
            match_seq = ''.join(['|' if r_base.upper() == q_base.upper() else '*' for (r_base, q_base) in zip(ref_piece, query_peace)]) # faster with "".join([list of str]) instead of +=
            matches += op_len 
            m_line.append(match_seq)
            r_index += op_len
            q_index += op_len

        elif op_type == 8:
            subs += op_len 


        elif op_type == 1:
            # insertion into reference
            r_line.append('-' * op_len)
            m_line.append(' ' * op_len)
            q_line.append(q_seq[q_index: q_index + op_len])
            #  only query index change
            q_index += op_len
            ins += op_len
        elif op_type == 2 or op_type == 3:
            # deletion from reference
            r_line.append(r_seq[r_index: r_index + op_len])
            m_line.append(' ' * op_len)
            q_line.append('-' * op_len)
            #  only ref index change
            r_index += op_len
            # print("here", r_index)
            if op_type == 2:
                del_ += op_len
        elif op_type == 4:
            # softclip
            pass
        elif op_type == 0:
            sys.exit("You have to use =/X cigar operators in sam file (M was detected). In minimap2 you can to provide --eqx flag to fix this.")


    r_line.append(r_end)
    m_line.append(m_end)
    q_line.append(q_end)    

    return "".join([s for s in r_line]), "".join([s for s in m_line]), "".join([s for s in q_line]), ins, del_, subs, matches


def get_aln_stats_per_read(sam_file, reads, refs):
    SAM_file = pysam.AlignmentFile(sam_file, "r", check_sq=False)
    references = SAM_file.references
    alignments = {}
    for read in SAM_file.fetch(until_eof=True):
        if read.flag == 0 or read.flag == 16:
            # print(read.is_reverse)
            # print(read.cigartuples)
            read_seq = reads[read.query_name]
            ref_seq = refs[read.reference_name]
            ref_alignment, m_line, read_alignment, ins, del_, subs, matches = cigar_to_seq_mm2_local(read, ref_seq, read_seq)
            # if read.query_name == 'b1d0ee62-7557-4645-8d1e-c1ccfb60c997_runid=8c239806e6f576cd17d6b7d532976b1fe830f9c6_sampleid=pcs109_sirv_mix2_LC_read=29302_ch=69_start_time=2019-04-12T22:47:30Z_strand=-':
            #     print(read.query_alignment_start)
            #     print(read.query_name, "primary", read.flag, read.reference_name) 
            #     print(ref_alignment)
            #     print(m_line)
            #     print(read_alignment)
            #     print(ins, del_, subs, matches)

            if read.query_name in alignments:
                print("BUG")
                sys.exit()
            
            alignments[read.query_name] = (ins, del_, subs, matches)
            # print()
            # return
        else:
            pass
            # print("secondary", read.flag, read.reference_name) 
    return alignments

def get_summary_stats(reads, quantile):
    tot_ins, tot_del, tot_subs, tot_match = 0, 0, 0, 0
    sorted_reads = sorted(reads.items(), key = lambda x: sum(x[1][0:3])/float(sum(x[1])) )
    for acc, (ins, del_, subs, matches) in sorted_reads[ : int(len(sorted_reads)*quantile)]:
        # (ins, del_, subs, matches) = reads[acc]

        tot_ins += ins
        tot_del += del_
        tot_subs += subs
        tot_match += matches

    sum_aln_bases = tot_ins + tot_del + tot_subs + tot_match

    return tot_ins, tot_del, tot_subs, tot_match, sum_aln_bases


def print_quantile_values(alignments_dict):

    alignments_sorted = sorted(alignments_dict.items(), key = lambda x: sum(x[1][0:3])/float(sum(x[1])) )
    print(alignments_sorted[-5:])

    sorted_error_rates = [ sum(tup[0:3])/float(sum(tup)) for acc, tup in alignments_sorted]

    insertions = [ tup[0]/float(sum(tup)) for acc, tup in alignments_sorted]
    deletions = [ tup[1]/float(sum(tup)) for acc, tup in alignments_sorted]
    substitutions = [ tup[2]/float(sum(tup)) for acc, tup in alignments_sorted]

    n = len(sorted_error_rates)
    quantiles = [0, 1.0/20, 1.0/10, 1.0/4, 1.0/2, 3.0/4, 9.0/10, 19.0/20, 1 ]
    quantile_errors = []
    quantile_insertions = []
    quantile_deletions = []
    quantile_substitutions = []

    for q in quantiles:
        if q == 1:
            quantile_errors.append(sorted_error_rates[int(q*n)-1])
            quantile_insertions.append(insertions[int(q*n)-1])
            quantile_deletions.append(deletions[int(q*n)-1])
            quantile_substitutions.append(substitutions[int(q*n)-1])
        else:
            quantile_errors.append(sorted_error_rates[int(q*n)])
            quantile_insertions.append(insertions[int(q*n)])
            quantile_deletions.append(deletions[int(q*n)])
            quantile_substitutions.append(substitutions[int(q*n)])

    # quantile_errors = [sorted_error_rates[0], sorted_error_rates[int(n/20)], sorted_error_rates[int(n/10)], 
    #             sorted_error_rates[int(n/4)], sorted_error_rates[int(n/2)], 
    #             sorted_error_rates[int(3*n/4)], sorted_error_rates[int(9*n/10)], sorted_error_rates[int(19*n/20)], 
    #             sorted_error_rates[-1]]

    return quantile_errors, quantile_insertions, quantile_deletions, quantile_substitutions


def cigar_to_seq(cigar, query, ref):
    cigar_tuples = []
    result = re.split(r'[=DXSMI]+', cigar)
    i = 0
    for length in result[:-1]:
        i += len(length)
        type_ = cigar[i]
        i += 1
        cigar_tuples.append((int(length), type_ ))

    r_index = 0
    q_index = 0
    q_aln = []
    r_aln = []
    for length_ , type_ in cigar_tuples:
        if type_ == "=" or type_ == "X":
            q_aln.append(query[q_index : q_index + length_])
            r_aln.append(ref[r_index : r_index + length_])

            r_index += length_
            q_index += length_
        
        elif  type_ == "I":
            # insertion w.r.t. reference
            r_aln.append('-' * length_)
            q_aln.append(query[q_index: q_index + length_])
            #  only query index change
            q_index += length_

        elif type_ == 'D':
            # deletion w.r.t. reference
            r_aln.append(ref[r_index: r_index + length_])
            q_aln.append('-' * length_)
            #  only ref index change
            r_index += length_
        
        else:
            print("error")
            print(cigar)
            sys.exit()

    return  "".join([s for s in q_aln]), "".join([s for s in r_aln])


def parasail_alignment(read, reference, x_acc = "", y_acc = "", match_score = 2, mismatch_penalty = -2, opening_penalty = 2, gap_ext = 1, ends_discrepancy_threshold = 0):
    user_matrix = parasail.matrix_create("ACGT", match_score, mismatch_penalty)
    result = parasail.sg_trace_scan_16(read, reference, opening_penalty, gap_ext, user_matrix)
    if result.saturated:
        print("SATURATED!")
        result = parasail.sg_trace_scan_32(read, reference, opening_penalty, gap_ext, user_matrix)
    if sys.version_info[0] < 3:
        cigar_string = str(result.cigar.decode).decode('utf-8')
    else:
        cigar_string = str(result.cigar.decode, 'utf-8')
    
    read_alignment, ref_alignment = cigar_to_seq(cigar_string, read, reference)
    return read_alignment, ref_alignment


def main(args):
    reads = { acc : seq for i, (acc, (seq, qual)) in enumerate(readfq(open(args.reads, 'r')))}
    corr_reads = { acc : seq for i, (acc, (seq, qual)) in enumerate(readfq(open(args.corr_reads, 'r')))}

    if args.align:
        for acc in reads:
            if acc not in corr_reads:
                print(acc, "Not in corrected reads")
            else:
                orig_seq = reads[acc]
                corr_seq = corr_reads[acc]
                read_alignment, ref_alignment = parasail_alignment(orig_seq, corr_seq)
                orig_dlen = [d_len for ch, d_len in  [(ch, len(list(_))) for ch, _ in itertools.groupby(read_alignment)] if ch == "-" ]
                corr_dlen = [d_len for ch, d_len in  [(ch, len(list(_))) for ch, _ in itertools.groupby(ref_alignment)] if ch == "-" ] 
                if corr_dlen:
                    max_orig_dlen = max( orig_dlen )
                else:
                    max_orig_dlen = 0
                if corr_dlen:
                    max_corr_dlen = max( corr_dlen )
                else:
                    max_corr_dlen = 0

                if max_corr_dlen > 10 or max_orig_dlen > 10:
                    print("orig", acc, read_alignment)
                    print("corr", acc, ref_alignment)
                    print()

    refs = { acc : seq for i, (acc, (seq, _)) in enumerate(readfq(open(args.refs, 'r')))}
    # print(refs)
    orig = get_aln_stats_per_read(args.orig_sam, reads, refs)
    corr = get_aln_stats_per_read(args.corr_sam, corr_reads, refs)
    print( "Reads successfully aligned:", len(orig),len(corr))
    quantile_tot_orig, quantile_insertions_orig, quantile_deletions_orig, quantile_substitutions_orig = print_quantile_values(orig)
    quantile_tot_corr, quantile_insertions_corr, quantile_deletions_corr, quantile_substitutions_corr = print_quantile_values(corr)

    # alignments_stats = get_summary_stats(alignments_dict, 1.0)
    # print("Original reads (total): ins:{0}, del:{1}, subs:{2}, match:{3}".format(*alignments_stats[:-1]), "tot aligned region (ins+del+subs+match):", alignments_stats[-1] )
    # print("Original reads percent:{0}, del:{1}, subs:{2}, match:{3}".format(*[round(100*float(s)/alignments_stats[-1] , 1) for s in alignments_stats[:-1]]))
    # print( "Num_aligned_reads", "Aligned bases", "tot_errors", "avg_error_rate", "median_read_error_rate", "upper_25_quant", "lower_25_quant", "min", "max")


    orig_stats = get_summary_stats(orig, 1.0)
    # print("Original reads (total): ins:{0}, del:{1}, subs:{2}, match:{3}".format(*orig_stats[:-1]), "tot aligned region (ins+del+subs+match):", orig_stats[-1] )
    # print("Original reads percent:{0}, del:{1}, subs:{2}, match:{3}".format(*[round(100*float(s)/orig_stats[-1] , 1) for s in orig_stats[:-1]]))

    corr_stats = get_summary_stats(corr, 1.0)
    # print("Corrected reads (total): ins:{0}, del:{1}, subs:{2}, match:{3}".format(*corr_stats[:-1]), "tot aligned region (ins+del+subs+match):", corr_stats[-1])
    # print("Corrected reads percent:{0}, del:{1}, subs:{2}, match:{3}".format(*[round(100*float(s)/corr_stats[-1] , 1) for s in corr_stats[:-1]]))


    # print( "Num_aligned_reads", "Aligned bases", "tot_errors", "avg_error_rate", "median_read_error_rate", "upper_25_quant", "lower_25_quant", "min", "max")
    # orig_sorted = sorted(orig.items(), key = lambda x: sum(x[1][0:3])/float(sum(x[1])) )
    # print(orig_sorted[-5:])

    # orig_sorted_error_rates = [ sum(tup[0:3])/float(sum(tup)) for acc, tup in orig_sorted]
    # orig_vals = [orig_sorted_error_rates[0], orig_sorted_error_rates[int(len(orig_sorted_error_rates)/20)], orig_sorted_error_rates[int(len(orig_sorted_error_rates)/10)], 
    #             orig_sorted_error_rates[int(len(orig_sorted_error_rates)/4)], orig_sorted_error_rates[int(len(orig_sorted_error_rates)/2)], 
    #             orig_sorted_error_rates[int(3*len(orig_sorted_error_rates)/4)], orig_sorted_error_rates[int(9*len(orig_sorted_error_rates)/10)], orig_sorted_error_rates[int(19*len(orig_sorted_error_rates)/20)], 
    #             orig_sorted_error_rates[-1]]


    # corr_sorted = sorted(corr.items(), key = lambda x: sum(x[1][0:3])/float(sum(x[1])) )
    # print(corr_sorted[-5:])
    # corr_sorted_error_rates = [ sum(tup[0:3])/float(sum(tup)) for acc, tup in corr_sorted]
    # corr_vals = [corr_sorted_error_rates[0],corr_sorted_error_rates[int(len(corr_sorted_error_rates)/20)], corr_sorted_error_rates[int(len(corr_sorted_error_rates)/10)],
    #              corr_sorted_error_rates[int(len(corr_sorted_error_rates)/4)], corr_sorted_error_rates[int(len(corr_sorted_error_rates)/2)],
    #               corr_sorted_error_rates[int(3*len(corr_sorted_error_rates)/4)], corr_sorted_error_rates[int(9*len(corr_sorted_error_rates)/10)], corr_sorted_error_rates[int(19*len(corr_sorted_error_rates)/20)],
    #               corr_sorted_error_rates[-1]]
    
    print("Distribution of error rates (Percent)")
    print("Reads, Best, top 5%, top 10%, top 25%, Median, top 75%, top 90%, top 95%, Worst")
    print("Original,{0},{1},{2},{3},{4},{5},{6},{7},{8}".format( *[round(100*round(x,3), 2) for x in quantile_tot_orig ] ))
    print("Corrected,{0},{1},{2},{3},{4},{5},{6},{7},{8}".format( *[round(100*round(x,3), 2) for x in quantile_tot_corr ] ))

    outfile = open(os.path.join(args.outfolder, "results.csv"), "w")
    outfile.write("Original,tot,{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13},{14}\n".format( *[round(100*round(x,3), 2) for x in quantile_tot_orig ], *orig_stats, len(orig)))
    outfile.write("Corrected,tot,{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13},{14}\n".format( *[round(100*round(x,3), 2) for x in quantile_tot_corr ], *corr_stats, len(corr)))
    
    outfile.write("Original,ins,{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13},{14}\n".format( *[round(100*round(x,3), 2) for x in quantile_insertions_orig ], *orig_stats, len(orig)))
    outfile.write("Corrected,ins,{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13},{14}\n".format( *[round(100*round(x,3), 2) for x in quantile_insertions_corr ], *corr_stats, len(corr)))

    outfile.write("Original,del,{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13},{14}\n".format( *[round(100*round(x,3), 2) for x in quantile_deletions_orig ], *orig_stats, len(orig)))
    outfile.write("Corrected,del,{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13},{14}\n".format( *[round(100*round(x,3), 2) for x in quantile_deletions_corr ], *corr_stats, len(corr)))

    outfile.write("Original,subs,{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13},{14}\n".format( *[round(100*round(x,3), 2) for x in quantile_substitutions_orig ], *orig_stats, len(orig)))
    outfile.write("Corrected,subs,{0},{1},{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13},{14}".format( *[round(100*round(x,3), 2) for x in quantile_substitutions_corr ], *corr_stats, len(corr)))

    outfile.close()

    print("Reads successfully aligned:", len(orig),len(corr))
    # print(orig_sorted)
    # print(",".join([s for s in orig_stats]))
    # print(",".join([s for s in corr_stats]))



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Evaluate pacbio IsoSeq transcripts.")
    parser.add_argument('orig_sam', type=str, help='Path to the original read file')
    parser.add_argument('corr_sam', type=str, help='Path to the corrected read file')
    parser.add_argument('reads', type=str, help='Path to the read file')
    parser.add_argument('corr_reads', type=str, help='Path to the corrected read file')
    parser.add_argument('refs', type=str, help='Path to the refs file')
    parser.add_argument('outfolder', type=str, help='Output path of results')
    parser.add_argument('--align', action= "store_true", help='Include pairwise alignment of original and corrected read.')

    args = parser.parse_args()

    outfolder = args.outfolder
    if not os.path.exists(outfolder):
        os.makedirs(outfolder)
    main(args)